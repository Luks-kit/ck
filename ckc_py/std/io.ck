// std/io.ck
// File I/O with Result-based error handling and automatic cleanup.

$import "std/result.ck";
$import "std/string.ck";

$include <stdio.h>
$extern {
    struct FILE;

    fn fopen(const char* path, const char* mode)            -> FILE*;
    fn fclose(FILE* f)                                      -> i32;
    fn fread(void* buf, usize size, usize n, FILE* f)       -> usize;
    fn fwrite(const void* buf, usize size, usize n, FILE* f)-> usize;
    fn fgets(char* buf, i32 n, FILE* f)                     -> char*;
    fn fputs(const char* s, FILE* f)                        -> i32;
    fn feof(FILE* f)                                        -> i32;
    fn ferror(FILE* f)                                      -> i32;
    fn fflush(FILE* f)                                      -> i32;
    fn fseek(FILE* f, i64 offset, i32 whence)               -> i32;
    fn ftell(FILE* f)                                       -> i64;
    fn rewind(FILE* f)                                      -> void;

    constexpr i32 SEEK_SET = 0;
    constexpr i32 SEEK_CUR = 1;
    constexpr i32 SEEK_END = 2;
};

// Owned file handle — $dinit closes automatically
struct File {
    FILE* handle;
    bool  owned;

    fn $init wrap(FILE* f, bool owned) -> Self {
        return { f, owned };
    }

    fn $dinit close() {
        if (self.owned && self.handle) {
            fclose(self.handle);
            self.handle = null;
        }
    }

    fn write_cstr(const char* s) -> bool {
        return fputs(s, self.handle) >= 0;
    }

    fn write_str(const String& s) -> bool {
        usize written = fwrite(s.ptr(), 1, s.length, self.handle);
        return written == s.length;
    }

    fn read_line(char* buf, i32 cap) -> bool {
        return fgets(buf, cap, self.handle) != null;
    }

    fn read_all() -> String {
        fseek(self.handle, 0, SEEK_END);
        i64 size = ftell(self.handle);
        rewind(self.handle);
        if (size <= 0) return String.from(null);
        String buf = String.with_cap((usize)size);
        usize n = fread(buf.storage.buffer, 1, (usize)size, self.handle);
        buf.storage.buffer[n] = 0;
        buf.length = n;
        return buf;
    }

    fn flush() -> void  { fflush(self.handle); }
    fn eof()   -> bool  { return feof(self.handle) != 0; }
    fn tell()  -> i64   { return ftell(self.handle); }
    fn seek(i64 offset, i32 whence) -> bool {
        return fseek(self.handle, offset, whence) == 0;
    }
};

// Open helpers — return Result so errors are explicit
fn file_open(const char* path, const char* mode) -> Result(File, char*) {
    FILE* f = fopen(path, mode);
    if (f == null) return Result(File, char*).err("fopen failed");
    return Result(File, char*).ok(File.wrap(f, true));
}

fn file_open_read(const char* path) -> Result(File, char*) {
    return file_open(path, "r");
}

fn file_open_write(const char* path) -> Result(File, char*) {
    return file_open(path, "w");
}

fn file_open_append(const char* path) -> Result(File, char*) {
    return file_open(path, "a");
}

// Convenience: read entire file to String in one call
fn io_read_file(const char* path) -> Result(String, char*) {
    auto r = file_open_read(path);
    $tag switch (r) {
        case (Result.err e): {
            return Result(String, char*).err(e);
        }
        case (Result.ok f): {
            $defer { f.close(); }
            String s = f.read_all();
            return Result(String, char*).ok(s);
        }
    }
}

// Convenience: write string to file in one call
fn io_write_file(const char* path, const String& content) -> bool {
    auto r = file_open_write(path);
    $tag switch (r) {
        case (Result.err e): {
            printf("io_write_file: %s\n", e);
            return false;
        }
        case (Result.ok f): {
            $defer { f.close(); }
            return f.write_str(content);
        }
    }
}
