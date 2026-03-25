// std/mem.ck
// Allocator interface and default heap allocator.
// Any struct implementing Allocator can be used as a template param
// wherever allocation is needed.

$include <stdlib.h>;

$interface
struct Allocator {
    fn alloc(usize size)                   -> void*;
    fn calloc(usize count, usize size)     -> void*;
    fn realloc(void* ptr, usize size)      -> void*;
    fn free(void* ptr)                     -> void;
};

// Default heap allocator — wraps libc malloc/calloc/realloc/free.
$implement(Allocator)
struct HeapAllocator {
    fn alloc(usize size) -> void* {
        return malloc(size);
    }

    fn calloc(usize count, usize size) -> void* {
        return calloc(count, size);
    }

    fn realloc(void* ptr, usize size) -> void* {
        return realloc(ptr, size);
    }

    fn free(void* ptr) -> void {
        free(ptr);
    }
};

$template(type T, Allocator A = HeapAllocator)
struct Box {
    T* data;
    A  alloc;

    // Allocates memory on the heap and moves 'val' into it.
    fn $init new(T val) -> Self {
        A a;
        T* p = a.alloc(sizeof(T));
        assert(p != null);
        
        // Move the value into the heap slot
        *p = val;
        
        return { p, a };
    }

    // Automatically called when the Box goes out of scope.
    fn $dinit drop() {
        if (self.data != null) {
            // 1. Recursively call destructor on the inner value
            $dinit(*self.data); 
            
            // 2. Free the actual memory slot
            self.alloc.free(self.data);
            self.data = null;
        }
    }

    // Access the inner value by reference.
    fn get() -> T& {
        assert(self.data != null);
        return *self.data;
    }

    // Unwraps the box, returning the value and freeing the heap slot 
    // without dropping the value itself.
    fn unbox() -> T {
        assert(self.data != null);
        T val = *self.data;
        
        // Free the pointer but DON'T call $dinit on the contents
        self.alloc.free(self.data);
        self.data = null;
        
        return val;
    }
};
