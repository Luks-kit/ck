
CC = gcc
CKC = ckc.py

CFLAGS = -std=c99 
SOURCE:=src
BUILD=build
TARGET=$(BUILD)/ckc
INSTALLDIR=/usr/local/bin/

.PHONY: all clean install

all: $(TARGET)

$(TARGET): $(SOURCE)/main.ck
	$(CKC) $(SOURCE)/main.ck -o $(BUILD)/tmp.c
	$(CC) $(BUILD)/tmp.c $(CFLAGS) -o $(TARGET)

test:

clean:
	rm $(BUILD)/* -r
install: $(TARGET)
	cp $(TARGET) $(INSTALLDIR)
	
