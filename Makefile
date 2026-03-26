
CC = gcc
CFLAGS = -g -std=c99
CKC = python3 ckc_py/ckc.py

SOURCE:=src
SOURCES:=$(wildcard $(SOURCE)/*.ck)
BUILD=build
TARGET=$(BUILD)/ckc
TESTSRC=$(wildcard tests/*.ck)
TESTOUT=$(TESTSRC:.ck=.c)
INSTALLDIR=/usr/local/bin/
MAINENTRY=$(SOURCE)/main.ck

.PHONY: all clean install test

all: $(TARGET)

$(TARGET): $(SOURCES)
	mkdir -p $(BUILD)
	$(CKC) $(MAINENTRY) -o $(BUILD)/tmp.c
	$(CC) $(BUILD)/tmp.c $(CFLAGS) -o $(TARGET)

test: $(TESTOUT)

tests/%.c: tests/%.ck | $(TARGET)
	$(TARGET) $< -o $@
clean:
	rm $(BUILD)/* -r
install: $(TARGET)
	cp $(TARGET) $(INSTALLDIR)
	
