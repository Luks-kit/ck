
CC = gcc
CFLAGS= -g -std=c99
CKC = ckc.py

SOURCE:=src
BUILD=build
TARGET=$(BUILD)/ckc
TESTSRC=$(wildcard tests/*.ck)
TESTOUT=$(TESTSRC:.ck=.c)
INSTALLDIR=/usr/local/bin/
MAINENTRY=$(SOURCE)/main.ck

.PHONY: all clean install

all: $(TARGET)

$(TARGET): $(MAINENTRY)
	$(CKC) $(MAINENTRY) -o $(BUILD)/tmp.c
	$(CC) $(BUILD)/tmp.c $(CFLAGS) -o $(TARGET)

test: $(TESTOUT)

$(TESTOUT): $(TESTSRC)
	$(TARGET) $< -o $@
clean:
	rm $(BUILD)/* -r
install: $(TARGET)
	cp $(TARGET) $(INSTALLDIR)
	
