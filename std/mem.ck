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
