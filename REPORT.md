# Raport z realizacji projektu

## Wyniki testów (dane syntetyczne, N = 12, sesje 120 s)
- **Przepływ end-to-end:** symulator C wysłał 8325 próbek (RR, EDA 4 Hz, BVP 64 Hz) przez TCP, odbiornik policzył
  9 okien i wynik jest identyczny z analizą wsadową (różnica maks. 0,0).
- **Determinizm timerów (10x przyspieszenie, bez RT):** opóźnienie średnie ok. 100 µs, maksymalne 3-15 ms.
  Na QNX z SCHED_FIFO oczekiwane znacznie mniejsze; pomiar do powtórzenia na docelowym systemie.
- **Liczba obiektów z obrazu:** korelacja z prawdą r = 0,89-0,93 w pojedynczej sesji, niedoszacowanie ok. 0,5-0,7
  obiektu (nakładające się obiekty).
- **Wskaźnik obciążenia vs ukryty profil stresu:** średnie r = 0,96 w oknach sesji.
- **Korelacja z Raw TLX (odpowiedzi syntetyczne):** RMSSD r = -0,97, HR Polar 0,94, liczba obiektów 0,94,
  EDA tonic 0,93, wskaźnik łączny 0,92. Najsłabsze: ruch głowy 0,52, SCR/min 0,63.

## Ograniczenie, które trzeba znać
Wysokie korelacje są **z konstrukcji**: dane fizjologiczne, obraz i odpowiedzi RTLX wygenerowano z tego samego
ukrytego profilu stresu. Pokazują, że potok działa i algorytmy wykrywają zmiany, a **nie** że system trafnie
ocenia obciążenie prawdziwych osób. Właściwa walidacja wymaga prawdziwych sesji. Przy N = 12 korelacje
mają szerokie przedziały ufności.

## Dalsze kroki
Prawdziwe dane w `data/` i `responses.csv`, kalibracja `REF`, test symulatora na QNX, rozszerzenie
`evaluate.py` o kodowane wyniki wywiadów (`peak_time_s`, `stress_1_5`).
