# Linux:  make        QNX:  make CC=qcc CFLAGS="-Vgcc_ntox86_64 -O2 -Wall"  (lub aarch64)
CC     ?= gcc
CFLAGS ?= -O2 -Wall -Wextra
LDLIBS ?= -lpthread
sim: sim.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)
clean:
	rm -f sim
