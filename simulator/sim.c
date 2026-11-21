/*
 * Symulator akwizycji danych (Moduł 1) - język C, POSIX / QNX Neutrino.
 *
 * Odtwarza historyczne pliki CSV (t,wartość) z urządzeń Polar i Empatica jako
 * strumienie "na żywo": każdy strumień ma własny wątek, własny priorytet
 * (SCHED_FIFO, szeregowanie wg częstotliwości - rate monotonic) oraz
 * deterministyczny timer absolutny (clock_nanosleep + TIMER_ABSTIME na
 * CLOCK_MONOTONIC). Próbki wysyłane są przez gniazdo TCP do modułu analitycznego.
 *
 * Część A (wczytywanie + timery):      load_stream(), wait_until(), lateness stats
 * Część B (wątki, priorytety, gniazda): start_thread(), send_line(), main()
 *
 * Protokół (tekstowy, jedna próbka = jedna linia):  NAZWA,t,wartość\n   ... END\n
 *
 * Użycie: sim <host> <port> <speed> plik:NAZWA [plik:NAZWA ...]
 *   speed - mnożnik czasu (1 = czas rzeczywisty, 10 = 10x szybciej)
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <pthread.h>
#include <sched.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>

#define MAX_STREAMS 8

typedef struct {
    char   name[32];
    char   path[256];
    double *t, *v;
    size_t n;
    int    prio;             /* priorytet SCHED_FIFO (0 = brak RT) */
    /* statystyki determinizmu */
    double lat_sum_us, lat_max_us;
    size_t sent;
    pthread_t th;
} stream_t;

static int             g_sock;
static pthread_mutex_t g_sock_mx = PTHREAD_MUTEX_INITIALIZER;
static struct timespec g_start;     /* wspólny moment zerowy */
static double          g_speed = 1.0;

/* ---------- Część A: wczytywanie i timery ---------- */

static int load_stream(stream_t *s)
{
    FILE *f = fopen(s->path, "r");
    if (!f) { perror(s->path); return -1; }
    char line[256];
    size_t cap = 1024;
    s->t = malloc(cap * sizeof(double)); s->v = malloc(cap * sizeof(double)); s->n = 0;
    if (!fgets(line, sizeof line, f)) { fclose(f); return -1; }   /* nagłówek */
    while (fgets(line, sizeof line, f)) {
        double t, v;
        if (sscanf(line, "%lf,%lf", &t, &v) != 2) continue;
        if (s->n == cap) {
            cap *= 2;
            s->t = realloc(s->t, cap * sizeof(double));
            s->v = realloc(s->v, cap * sizeof(double));
        }
        s->t[s->n] = t; s->v[s->n] = v; s->n++;
    }
    fclose(f);
    return s->n ? 0 : -1;
}

static struct timespec deadline_for(double t_sample)
{
    double dt = t_sample / g_speed;
    struct timespec d = g_start;
    d.tv_sec  += (time_t)dt;
    d.tv_nsec += (long)((dt - (time_t)dt) * 1e9);
    if (d.tv_nsec >= 1000000000L) { d.tv_sec++; d.tv_nsec -= 1000000000L; }
    return d;
}

static double ts_diff_us(struct timespec a, struct timespec b)
{
    return (a.tv_sec - b.tv_sec) * 1e6 + (a.tv_nsec - b.tv_nsec) / 1e3;
}

/* ---------- Część B: wątki, priorytety, gniazda ---------- */

static int send_line(const char *buf, size_t len)
{
    pthread_mutex_lock(&g_sock_mx);          /* jedna linia = jedna atomowa operacja */
    size_t off = 0;
    while (off < len) {
        ssize_t r = send(g_sock, buf + off, len - off, MSG_NOSIGNAL);
        if (r < 0) { if (errno == EINTR) continue; pthread_mutex_unlock(&g_sock_mx); return -1; }
        off += (size_t)r;
    }
    pthread_mutex_unlock(&g_sock_mx);
    return 0;
}

static void *stream_thread(void *arg)
{
    stream_t *s = arg;
    char buf[96];
    for (size_t i = 0; i < s->n; i++) {
        struct timespec dl = deadline_for(s->t[i]), now;
        while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &dl, NULL) == EINTR) ;
        clock_gettime(CLOCK_MONOTONIC, &now);
        double lat = ts_diff_us(now, dl);
        s->lat_sum_us += lat;
        if (lat > s->lat_max_us) s->lat_max_us = lat;
        int len = snprintf(buf, sizeof buf, "%s,%.4f,%.5f\n", s->name, s->t[i], s->v[i]);
        if (send_line(buf, (size_t)len) < 0) break;
        s->sent++;
    }
    return NULL;
}

static int start_thread(stream_t *s)
{
    pthread_attr_t at;
    pthread_attr_init(&at);
    int rt_ok = 0;
    if (s->prio > 0) {
        struct sched_param sp = { .sched_priority = s->prio };
        pthread_attr_setinheritsched(&at, PTHREAD_EXPLICIT_SCHED);
        pthread_attr_setschedpolicy(&at, SCHED_FIFO);
        pthread_attr_setschedparam(&at, &sp);
        rt_ok = (pthread_create(&s->th, &at, stream_thread, s) == 0);
        if (!rt_ok)
            fprintf(stderr, "[%s] brak uprawnień do SCHED_FIFO (prio %d) - zwykły wątek\n", s->name, s->prio);
    }
    if (!rt_ok) {
        pthread_attr_destroy(&at); pthread_attr_init(&at);
        if (pthread_create(&s->th, &at, stream_thread, s) != 0) return -1;
    }
    pthread_attr_destroy(&at);
    return rt_ok;
}

static int connect_to(const char *host, int port)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = { .sin_family = AF_INET, .sin_port = htons((uint16_t)port) };
    if (inet_pton(AF_INET, host, &a.sin_addr) != 1) { fprintf(stderr, "zły adres IP\n"); return -1; }
    for (int tries = 0; tries < 50; tries++) {              /* czekaj na odbiornik */
        if (connect(fd, (struct sockaddr *)&a, sizeof a) == 0) {
            int one = 1; setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
            return fd;
        }
        usleep(200000);
    }
    perror("connect"); return -1;
}

int main(int argc, char **argv)
{
    if (argc < 5) {
        fprintf(stderr, "użycie: %s host port speed plik:NAZWA ...\n", argv[0]);
        return 2;
    }
    g_speed = atof(argv[3]);
    if (g_speed <= 0) { fprintf(stderr, "speed musi być > 0\n"); return 2; }

    stream_t st[MAX_STREAMS]; memset(st, 0, sizeof st);
    int ns = argc - 4; if (ns > MAX_STREAMS) ns = MAX_STREAMS;
    for (int i = 0; i < ns; i++) {
        char *sep = strrchr(argv[4 + i], ':');
        if (!sep) { fprintf(stderr, "oczekiwano plik:NAZWA\n"); return 2; }
        *sep = 0;
        snprintf(st[i].path, sizeof st[i].path, "%s", argv[4 + i]);
        snprintf(st[i].name, sizeof st[i].name, "%s", sep + 1);
        if (load_stream(&st[i]) < 0) return 1;
        /* rate monotonic: im gęstszy strumień, tym wyższy priorytet */
        double span = st[i].t[st[i].n - 1] - st[i].t[0];
        double rate = span > 0 ? st[i].n / span : 1;
        st[i].prio = rate > 32 ? 30 : rate > 2 ? 20 : 10;
        fprintf(stderr, "[%s] %zu próbek, ~%.1f Hz, prio %d\n", st[i].name, st[i].n, rate, st[i].prio);
    }

    g_sock = connect_to(argv[1], atoi(argv[2]));
    if (g_sock < 0) return 1;

    clock_gettime(CLOCK_MONOTONIC, &g_start);
    g_start.tv_nsec += 300000000L;                          /* start za 300 ms */
    if (g_start.tv_nsec >= 1000000000L) { g_start.tv_sec++; g_start.tv_nsec -= 1000000000L; }

    for (int i = 0; i < ns; i++)
        if (start_thread(&st[i]) < 0) { perror("pthread_create"); return 1; }
    for (int i = 0; i < ns; i++) pthread_join(st[i].th, NULL);

    send_line("END\n", 4);
    for (int i = 0; i < ns; i++)
        fprintf(stderr, "[%s] wysłano %zu, opóźnienie timera: śr. %.0f us, max %.0f us\n",
                st[i].name, st[i].sent, st[i].sent ? st[i].lat_sum_us / st[i].sent : 0.0, st[i].lat_max_us);
    close(g_sock);
    return 0;
}
