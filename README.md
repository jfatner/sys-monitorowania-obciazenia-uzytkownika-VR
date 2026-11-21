# System monitorowania obciążenia użytkownika VR

Implementacja trzech modułów z opisu projektu. **Uwaga: całość działa na danych syntetycznych**
(brak prawdziwych plików Polar/Empatica, nagrania z gogli i ankiet) - patrz „Co zastąpić".

## Struktura
| Katalog | Zawartość |
|---|---|
| `data_gen/gen_data.py` | generator 12 sesji (RR Polar, EDA+BVP Empatica, wideo 320x240@10 fps, prawda terenowa) |
| `simulator/sim.c` | **Moduł 1** (C): wczytanie CSV, wątek na strumień, SCHED_FIFO wg częstotliwości, timery absolutne `clock_nanosleep(TIMER_ABSTIME)`, wysyłka TCP, statystyki opóźnień |
| `analysis/physio.py` | **Moduł 2**: filtry Butterwortha, DFT/FFT (`dft_naive` do weryfikacji), HRV (RMSSD, SDNN, LF/HF), EDA (tonic, SCR), HR z BVP |
| `analysis/video.py` | **Moduł 2**: rozmycie Gaussa, Otsu, morfologia, transformata odległości, Canny; liczba obiektów; kompensacja ruchu głowy, ruchome obiekty, energia i częstotliwość ruchu |
| `analysis/receiver.py` | odbiornik TCP, okna 30 s co 10 s, wynik na żywo |
| `analysis/session.py` | okna i obiektywny wskaźnik obciążenia 0-100 |
| `evaluation/` | **Moduł 3**: formularz RTLX (`rtlx_form.html`), scenariusz wywiadu, `evaluate.py` (korelacje Pearsona/Spearmana) |

Podział osób z dokumentu jest zachowany w komentarzach nagłówkowych plików.

## Uruchomienie
```bash
python3 data_gen/gen_data.py --out data --n 12 --dur 120   # ~1 min
./run_demo.sh P01 10            # symulator C -> TCP -> odbiornik (10x szybciej niż czas rzeczywisty)
python3 evaluation/gen_synthetic_responses.py              # tylko do testu; pomiń przy prawdziwych danych
python3 evaluation/evaluate.py                             # korelacje, wykresy w results/
```
Na QNX: `make CC=qcc CFLAGS="-Vgcc_ntox86_64 -O2 -Wall" LDLIBS=""` (pthread jest w libc). Bez uprawnień
do SCHED_FIFO symulator ostrzega i działa na zwykłych wątkach.

## Co zastąpić prawdziwymi danymi
1. Pliki `polar_rr.csv` (t,rr_ms), `empatica_eda.csv` (t,eda_uS), `empatica_bvp.csv` (t,bvp), `video.avi` w `data/Pxx/`.
2. `evaluation/responses.csv` z formularza RTLX (gdy istnieje, ma pierwszeństwo przed `_SYNTHETIC`).
3. Zakresy `REF` w `analysis/session.py` i progi w `video.py` - strojone ręcznie pod dane syntetyczne.
