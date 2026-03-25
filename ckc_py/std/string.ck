// std/string.ck
// Managed UTF-8 string type.
// length = byte length, excluding null terminator
// cap    = usable byte capacity, excluding null terminator

$include <stdlib.h>;
$include <string.h>;
$include <assert.h>;

$tag union StringStorage {
    const char* literal;
    char* buffer;
    
    fn $init lit(const char* l) -> Self {
        return {.tag_ = StringStorage_literal_, .literal = l };
    }
    
    fn $init buf(char* b) -> Self {
        return {.tag_ = StringStorage_buffer_, .buffer = b };
    }
};

struct String {
    StringStorage storage;
    usize length;
    usize cap;

    fn $init from(const char* s) -> Self {
        if (s == null) return { StringStorage.lit(null), 0, 0 };
        
        usize len = strlen(s);
        char* p = malloc(len + 1);
        assert(p != null);
        memcpy(p, s, len + 1);

        return { StringStorage.buf(p), len, len };
    }

    fn $init lit(const char* s) -> Self {
        if (s == null) return { StringStorage.lit(null), 0, 0 };
        return { StringStorage.lit(s), strlen(s), 0 };
    }

    fn $init with_cap(usize cap) -> Self {
        char* p = malloc(cap + 1);
        assert(p != null);
        p[0] = 0;
        return { StringStorage.buf(p), 0, cap };
    }

    fn $dinit drop() {
        // Only free if we actually own a heap buffer
        if (self.storage.tag_ == StringStorage_buffer_ && self.storage.buffer != null) {
            free((void*)self.storage.buffer);
        }
        self.storage = StringStorage.lit(null);
        self.length = 0;
        self.cap = 0;
    }

    fn ptr() -> const char* {
        if (self.storage.tag_ == StringStorage_buffer_) {
            return self.storage.buffer == null ? "" : self.storage.buffer;
        }
        return self.storage.literal == null ? "" : self.storage.literal;
    }

    fn eq(const String& other) -> bool {
        if (self.length != other.length) return false;
        if (self.length == 0) return true; // Works because if other.length is not 0, previous if immediately returns false
        
        // Final check: compare the actual bytes
        // We use .ptr() to abstract away the StringStorage union
        return memcmp(self.ptr(), other.ptr(), self.length) == 0;
    }

    fn eq_cstr(const char* s) -> bool {
        if (s == null) return self.length == 0;
        if(strlen(s) != self.length) return false;

        return strcmp(self.ptr(), s) == 0;
    }

    fn append(const String& other) -> void {
        if (other.length == 0) return;
        self._grow(self.length + other.length);
        
        char* dst = self._mut_ptr();
        memcpy(dst + self.length, other.ptr(), other.length);
        self.length += other.length;
        dst[self.length] = 0;
    }

    fn clear() -> void {
        if (self.storage.tag_ == StringStorage_literal_) {
            self.storage = StringStorage.lit("");
            self.length = 0;
            self.cap = 0;
        } else if (self.storage.buffer != null) {
            self.storage.buffer[0] = 0;
            self.length = 0;
        }
    }
    
    fn at(usize i) -> char {
        assert(i < self.length);
        return self.ptr()[i];
    }
    
    fn clone() -> String { 
        return String.from(self.ptr());
    }

    fn $init from_range(const char* src, usize len) -> Self {
        if (src == null) return { StringStorage.lit(null), 0, 0 };
        
        char* p = malloc(len + 1);
        assert(p != null);
        memcpy(p, src, len);
        p[len] = 0;

        return { StringStorage.buf(p), len, len };
    }

    // ── Internal Helpers ──────────────────────────────────────────────────────

    fn _mut_ptr() -> char* {
        if (self.storage.tag_ == StringStorage_literal_) {
            self._promote_to_buffer(self.length);
        }
        return self.storage.buffer;
    }

    fn _promote_to_buffer(usize target_cap) -> void {
        const char* old_ptr = self.storage.literal;
        char* new_buf = malloc(target_cap + 1);
        assert(new_buf != null);

        if (old_ptr != null && self.length > 0) {
            memcpy(new_buf, old_ptr, self.length);
        }
        new_buf[self.length] = 0;

        self.storage = StringStorage.buf(new_buf);
        self.cap = target_cap;
    }

    fn _grow(usize needed_len) -> void {
        if (self.storage.tag_ == StringStorage_literal_) {
            self._promote_to_buffer(needed_len);
            return;
        }

        if (self.cap >= needed_len) return;

        usize new_cap = self.cap == 0 ? needed_len : self.cap * 2;
        if (new_cap < needed_len) new_cap = needed_len;

        char* p = realloc((void*)self.storage.buffer, new_cap + 1);
        assert(p != null);

        self.storage = StringStorage.buf(p);
        self.cap = new_cap;
    }
};
