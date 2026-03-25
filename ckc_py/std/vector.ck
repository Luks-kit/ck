// std/vector.ck
// Generic growable array with pluggable allocator.

$include <stdlib.h>;
$include <assert.h>;
$import "std/mem.ck";

$template(type T, Allocator A = HeapAllocator)
struct vector {
    T*    data;
    usize len;
    usize cap;
    A     alloc;

    fn $init new(usize init_cap) -> Self {
        A a;
        T* buf = null;
        if (init_cap > 0) {
            buf = a.alloc(init_cap * sizeof(T));
        }
        return { buf, 0, init_cap, a };
    }

    fn $init with_allocator(usize init_cap, A a) -> Self {
        T* buf = null;
        if (init_cap > 0) {
            buf = a.alloc(init_cap * sizeof(T));
        }
        return { buf, 0, init_cap, a };
    }

    fn $dinit delete() {
        if (self.data) {
            for (usize i = 0; i < self.len; i++) {
                $dinit(self.data[i]);   // calls T's $dinit if T has one, else no-op
            }
            self.alloc.free(self.data);
            self.data = null;
        }
    }

    fn push(T val) -> void {
        if (self.len >= self.cap) {
            self.cap = self.cap == 0 ? 8 : self.cap * 2;
            self.data = self.alloc.realloc(self.data, self.cap * sizeof(T));
        }
        self.data[self.len++] = val;
    }

    fn get(usize i) -> T& {
        assert(i < self.len);
        return self.data[i];
    }

    fn set(usize i, T val) -> void {
        assert(i < self.len);
        self.data[i] = val;
    }

    fn pop() -> T {
        assert(self.len > 0);
        return self.data[--self.len];
    }

    fn clear() -> void {
        self.len = 0;
    }
};
