# System monitorowania obciążenia użytkownika VR

Ocena obciążenia (stresu, zmęczenia) użytkownika aplikacji VR na podstawie:
- **Polar**: tętno i zmienność rytmu serca (HRV),
- **Empatica**: przewodnictwo skóry (EDA), tętno optyczne (BVP), ruch ręki (ACC),
- **obrazu z gogli** (Meta Quest przez OBS): zagęszczenie obiektów, ruch sceny i głowy,
- **kamery laptopa**: ruch użytkownika,

walidowana ankietą Raw NASA-TLX i krótkim wywiadem.

## Wersje
| Wersja | Tag | Obsługa |
|---|---|---|
| 1 | `v1.0` | skrypty uruchamiane po kolei w terminalu |
| 2 | `v2.0` | aplikacja okienkowa (tkinter) uruchamiająca te same skrypty |
| 3 | `v3.0` | aplikacja w przeglądarce (lokalny serwer, działa bez internetu) |

Analiza (moduły 1-3) jest we wszystkich wersjach taka sama - różni się tylko sposób obsługi.
Starsze wersje: zakładka **Tags** na GitHubie albo `git checkout v1.0`.

## Przebieg pracy - aplikacja
Uruchom w terminalu PyCharma (środowisko vr):
```
python app.py
```
Aplikacja otworzy się w przeglądarce (działa lokalnie, bez internetu). Terminal zostaw otwarty -
zamknięcie aplikacji to Ctrl+C. Po lewej lista uczestników, dla wybranego uczestnika pięć kroków:

1. **Nagraj sesję** - otwiera okno podglądu kolegi (gogle + kamera + maska różnic).
   W oknie: **R** start/stop, **T** start zadania (koniec spoczynku), **M** synchronizacja, **Q** koniec.
2. **Pliki z opasek** - przeciągnij pliki Polara / folder Empatiki na kartę albo wybierz je przyciskiem.
3. **Fragment do analizy** - od-do (mm:ss); oś czasu pokazuje spoczynek i fragment.
4. **Ankieta** - formularz otwiera się w nowej karcie i po „Zapisz” trafia prosto do folderu uczestnika.
5. **Analizuj** - pasek postępu z szacowanym czasem; wyniki (kafelki, wykres, klatki) pojawiają się od razu niżej.

Zakładka **Zestawienie** - korelacje wyników z ankietami dla wszystkich uczestników.
Koło zębate - numery kamer i test, które działają.
Klasyczna wersja w okienkach: `python app_tk.py`.

Te same kroki da się uruchomić skryptami (bez aplikacji):
`nagrywanie/record_session.py --id P01`, `analysis/process_session.py sesje/P01`, `evaluation/evaluate.py sesje`.
Część czasu rzeczywistego (symulator C na QNX/Linux odtwarzający nagrane dane jak na żywo): `./run_stream.sh sesje/P01 1`.

Szczegóły przeprowadzenia sesji: **[PROTOKOL_SESJI.md](PROTOKOL_SESJI.md)**.

## Folder jednej sesji
```
sesje/P01/
  app.mp4, webcam.mp4, frames.csv, events.csv, info.json   <- z nagrywarki (krok 1)
  polar/      <- plik(i) z Polara, bez zmian nazw
  empatica/   <- folder dnia z raw_data (.avro, EmbracePlus) albo eksport E4
  ankieta_P01.json                                          <- z formularza ankiety
  wyniki/                                                   <- tworzy analiza
    cechy.csv          cechy w oknach 30 s co 10 s + wskaźnik obciążenia 0-100
    podsumowanie.json  spoczynek, średnie z zadania, szczyt, ostrzeżenia
    przebieg.png       wykres całej sesji
    obraz_app.csv, obraz_webcam.csv, strumienie/*.csv
```
**Nazwy folderów:** używajcie kodów (P01, P02, …), a listę „kod → imię i nazwisko” trzymajcie osobno,
poza projektem (np. tylko u prowadzącego). Nagrania z kamerki i dane fizjologiczne to dane osobowe,
a kod w nazwie folderu ułatwia też dzielenie się wynikami bez ujawniania, kto jest kim.

## Struktura kodu
| Plik | Moduł | Zawartość |
|---|---|---|
| `simulator/sim.c` | 1 | C, POSIX/QNX: wątek na strumień, SCHED_FIFO wg częstotliwości, timery `clock_nanosleep(TIMER_ABSTIME)`, wysyłka TCP |
| `nagrywanie/record_session.py` | – | nagrywarka (na bazie podglądu kolegi): czyste wideo + czas każdej klatki + znaczniki |
| `analysis/importers.py` | 2 | wczytanie eksportów E4 i Polara, czasy bezwzględne |
| `analysis/physio.py` | 2 | filtry, DFT, HRV (RMSSD, SDNN, LF/HF), EDA (tonic, SCR), BVP, ACC |
| `analysis/video.py` | 2 | segmentacja i liczba obiektów, przepływ optyczny (ruch głowy vs ruch elementów), ruch użytkownika z kamerki |
| `analysis/session.py` | 2 | synchronizacja, okna, wskaźnik obciążenia względem spoczynku |
| `analysis/config.py` | 2 | **wszystkie progi i wagi w jednym miejscu** |
| `analysis/process_session.py` | 2 | analiza sesji, wykres, podsumowanie |
| `analysis/receiver.py` | 2 | odbiór danych z symulatora C na żywo |
| `app.py`, `web/` | – | aplikacja: lokalny serwer (sam Python) + interfejs w przeglądarce |
| `app_tk.py` | – | wersja okienkowa (z wersji 2) |
| `evaluation/ankieta.html` | 3 | formularz RTLX + wywiad (z aplikacji zapis prosto do sesji, osobno - plik JSON) |
| `evaluation/evaluate.py` | 3 | korelacje Pearsona/Spearmana, zgodność momentu szczytu |

## Jak liczony jest wskaźnik obciążenia
Każda osoba jest porównywana **sama ze sobą**: z okresem spoczynku na początku sesji (od startu
nagrania do znacznika T, z pominięciem pierwszych 30 s - reakcji na założenie gogli). Dla każdej cechy liczona jest zmiana względem spoczynku i przeliczana na 0–1,
np. +25 bpm tętna = 1, spadek RMSSD o 60% = 1, dwukrotny wzrost EDA = 1. Cechy są uśredniane w grupach:
**fizjologia** (waga 0,6), **ruch** (0,2), **scena** (0,2) i dają wskaźnik 0–100.
Skale i wagi to założenia (HEURYSTYKA w `config.py`) - do sprawdzenia po pierwszych sesjach.

## Stan obsługi urządzeń (po testach na prawdziwych plikach)
- **Polar Verity Sense** przez aplikację Polar Sensor Logger: zaznaczać **HR + PPI**. Działa. Uderzenia oznaczone
  przez opaskę jako zakłócone (`blocker`) są odrzucane, a „zamrożone” HR (stała wartość > 30 s, gdy czujnik zgubi
  puls) pomijane. Przy dużym ruchu ręki HRV nie da się policzyć - program to zgłasza w ostrzeżeniach.
- **Empatica EmbracePlus**: czytane są surowe pliki `.avro` (folder `raw_data` z chmury Empatiki, pobierany kluczami
  Data Access Keys) - bez dodatkowych bibliotek. Do `sesje/Pxx/empatica/` wrzucacie folder z dnia sesji
  (np. `participant_data/2026-11-17`) albo same pliki `.avro`; folder `digital_biomarkers` jest pomijany.
  **Uwaga:** w pierwszych pobranych plikach EDA i BVP były puste - te czujniki trzeba włączyć w konfiguracji badania
  w Care Lab Portal. Do tego czasu z Empatiki używany jest akcelerometr, temperatura i znaczniki przycisku (synchronizacja).
  Format E4 (CSV) też jest obsługiwany.
- **Liczba obiektów** to przybliżenie (obszary ograniczone krawędziami). Sprawdźcie na `wyniki/klatki/`, czy obrysy
  mają sens na waszej scenie; próg w `analysis/config.py` (`MIN_OBJ_AREA`).

## Ograniczenia interpretacji
Przy kilkunastu osobach korelacje mają szerokie przedziały ufności, a `evaluate.py` liczy wiele par
naraz, więc część „istotnych” wyników może być przypadkowa. W sprawozdaniu warto wskazać z góry
2–3 główne hipotezy (np. `load_index` vs RTLX, `hr_delta` vs RTLX) i to je traktować jako test.

## Środowisko
Python 3.12: `numpy>=2 scipy pandas matplotlib` (conda-forge) + `pip install opencv-python`.
Symulator w C: Linux/WSL (`make -C simulator`) albo QNX (`make CC=qcc CFLAGS="-Vgcc_ntox86_64 -O2 -Wall" LDLIBS=""`).
