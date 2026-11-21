# Protokół jednej sesji

## Przed uczestnikiem
- [ ] Opaski naładowane; czas w telefonie i laptopie ustawiany automatycznie.
- [ ] OBS: obraz z Questa widoczny, kliknięte **Start Virtual Camera**.
- [ ] Kamera laptopa skierowana na uczestnika (głowa i ręce w kadrze).
- [ ] Wolny kod uczestnika (P01, P02…); lista kod → osoba osobno, poza projektem.
- [ ] Podpisana zgoda uczestnika (nagranie z kamerki, dane z opasek).

## Sesja
1. Podczas tłumaczenia zadania (kilka minut przed VR) załóż opaski i **włącz w nich zapis**:
   - Polar Verity Sense: wysoko na ramieniu ręki mniej używanej w grze, ciasno; Polar Sensor Logger: **HR + PPI**, Save data.
   - Empatica: na nadgarstek, ciasno.
   Opaski potrzebują ok. 30 s, żeby złapać puls - dlatego zapis startuje wcześniej, nie w momencie wejścia do VR.
2. Uczestnik zakłada gogle. `python nagrywanie/record_session.py --id P01`, w oknie podglądu **R**.
3. **Spoczynek ok. 2 min**: uczestnik siedzi spokojnie w neutralnej scenie (menu/lobby gry), nic nie robi.
4. **T** w oknie podglądu - start zadania w grze.
5. Koniec: **R** (stop) albo **Q**. Zatrzymaj zapis w opaskach.

## Zaraz po sesji
1. Otwórz `evaluation/ankieta.html`. Uczestnik wypełnia suwaki, prowadzący wpisuje odpowiedzi z wywiadu.
   Moment największego napięcia podaj jako mm:ss od startu nagrania. **Zapisz** i przenieś `ankieta_P01.json` do `sesje/P01/`.

## Po zajęciach
1. Skopiuj do `sesje/P01/polar/` pliki `_HR.txt` i `_PPI.txt` z tej sesji (z folderu zapisu Polar Sensor Loggera w telefonie).
2. Skopiuj do `sesje/P01/empatica/` surowe dane z tej sesji (folder dnia z `raw_data`).
3. Obejrzyj `sesje/P01/app.mp4`, wybierz fragment i dopisz go do `info.json`: `"fragment_s": [od, do]` w sekundach.
4. `python analysis/process_session.py sesje/P01` - obejrzyj `wyniki/przebieg.png`, ostrzeżenia i `wyniki/klatki/`.
