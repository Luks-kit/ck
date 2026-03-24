// std/hashmap.ck
// Generic open-addressing hashmap with linear probing.
// Hash and equality functions are passed as function pointers.
//
// Usage:
//   auto m = hashmap(str, i32).new(str_hash, str_eq);
//   m.insert("hello", 42);
//   auto r = m.get("hello");   // Result(i32, char*)

$include <stdlib.h>;
$include <string.h>;
$include <assert.h>;
$import "std/result.ck";

// Built-in hash functions for common key types
fn hash_i32(i32 key) -> usize {
    usize k = (usize)key;
    k = ((k >> 16) ^ k) * 0x45d9f3bUL;
    k = ((k >> 16) ^ k) * 0x45d9f3bUL;
    k = (k >> 16) ^ k;
    return k;
}

fn hash_u32(u32 key) -> usize {
    usize k = (usize)key;
    k = ((k >> 16) ^ k) * 0x45d9f3bUL;
    k = ((k >> 16) ^ k) * 0x45d9f3bUL;
    k = (k >> 16) ^ k;
    return k;
}

fn hash_usize(usize key) -> usize {
    key = ((key >> 30) ^ key) * 0xbf58476d1ce4e5b9UL;
    key = ((key >> 27) ^ key) * 0x94d049bb133111ebUL;
    key = (key >> 31) ^ key;
    return key;
}

fn hash_cstr(const char* key) -> usize {
    usize h = 14695981039346656037UL;
    const char* p = key;
    while (p[0]) {
        h = h ^ (usize)p[0];
        h = h * 1099511628211UL;
        p = p + 1;
    }
    return h;
}

fn eq_i32(i32 a, i32 b) -> bool { return a == b; }
fn eq_u32(u32 a, u32 b) -> bool { return a == b; }
fn eq_usize(usize a, usize b) -> bool { return a == b; }
fn eq_cstr(const char* a, const char* b) -> bool { return strcmp(a, b) == 0; }

$import "std/string.ck";

fn hash_string(String s) -> usize {
    return hash_cstr(s.ptr());
}

fn eq_string(String a, String b) -> bool {
    return a.eq(b);
}

// Entry state
enum EntryState {
    Empty,
    Occupied,
    Tombstone,
};

$template(type K, type V)
struct hashmap {
    K*    keys;
    V*    vals;
    u8*   states;     // EntryState per slot
    usize cap;        // always power of 2
    usize len;        // occupied entries
    usize tombstones;
    fn(K) -> usize         hash_fn;
    fn(K, K) -> bool       eq_fn;

    fn $init new(fn(K) -> usize hfn, fn(K, K) -> bool efn) -> Self {
        usize init_cap = 16;
        K*  ks = malloc(init_cap * sizeof(K));
        V*  vs = malloc(init_cap * sizeof(V));
        u8* st = calloc(init_cap, sizeof(u8));  // all Empty (0)
        return { ks, vs, st, init_cap, 0, 0, hfn, efn };
    }

    fn $dinit free() {
        if (self.keys) {
            free(self.keys);
            free(self.vals);
            free(self.states);
            self.keys   = null;
            self.vals   = null;
            self.states = null;
        }
    }

    // Insert or update. Returns true if inserted (new key), false if updated.
    fn insert(K key, V val) -> bool {
        // resize if load > 75%
        if ((self.len + self.tombstones + 1) * 4 >= self.cap * 3) {
            self._resize(self.cap * 2);
        }
        usize slot = self._find_slot(key);
        bool is_new = self.states[slot] != EntryState.Occupied;
        if (self.states[slot] == EntryState.Tombstone) {
            self.tombstones--;
        }
        self.keys[slot]   = key;
        self.vals[slot]   = val;
        self.states[slot] = EntryState.Occupied;
        if (is_new) self.len++;
        return is_new;
    }

    // Get a value by key. Returns Result.ok(V) or Result.err("not found").
    fn get(K key) -> Result(V, char*) {
        usize slot = self._lookup(key);
        if (slot == self.cap)
            return Result(V, char*).err("not found");
        return Result(V, char*).ok(self.vals[slot]);
    }

    // Get a reference to a value. Returns null if not found.
    fn get_ptr(K key) -> V* {
        usize slot = self._lookup(key);
        if (slot == self.cap) return null;
        return &self.vals[slot];
    }

    // Returns true if key exists.
    fn contains(K key) -> bool {
        return self._lookup(key) != self.cap;
    }

    // Remove a key. Returns true if it was present.
    fn remove(K key) -> bool {
        usize slot = self._lookup(key);
        if (slot == self.cap) return false;
        self.states[slot] = EntryState.Tombstone;
        self.tombstones++;
        self.len--;
        return true;
    }

    fn count() -> usize { return self.len; }

    // ── internals ─────────────────────────────────────────────────────────────

    // Find slot for insertion (stops at Empty or Tombstone after first Tombstone seen)
    fn _find_slot(K key) -> usize {
        usize mask      = self.cap - 1;
        usize idx       = self.hash_fn(key) & mask;
        usize tombstone = self.cap;   // sentinel: no tombstone seen
        for (usize i = 0; i < self.cap; i++) {
            usize slot = (idx + i) & mask;
            if (self.states[slot] == EntryState.Empty) {
                return tombstone != self.cap ? tombstone : slot;
            }
            if (self.states[slot] == EntryState.Tombstone) {
                if (tombstone == self.cap) tombstone = slot;
            } else {
                if (self.eq_fn(self.keys[slot], key)) return slot;
            }
        }
        return tombstone != self.cap ? tombstone : self.cap;
    }

    // Find slot for lookup (returns self.cap if not found)
    fn _lookup(K key) -> usize {
        usize mask = self.cap - 1;
        usize idx  = self.hash_fn(key) & mask;
        for (usize i = 0; i < self.cap; i++) {
            usize slot = (idx + i) & mask;
            if (self.states[slot] == EntryState.Empty) return self.cap;
            if (self.states[slot] == EntryState.Occupied) {
                if (self.eq_fn(self.keys[slot], key)) return slot;
            }
        }
        return self.cap;
    }

    fn _resize(usize new_cap) -> void {
        K*  new_keys   = malloc(new_cap * sizeof(K));
        V*  new_vals   = malloc(new_cap * sizeof(V));
        u8* new_states = calloc(new_cap, sizeof(u8));
        usize mask = new_cap - 1;

        for (usize i = 0; i < self.cap; i++) {
            if (self.states[i] != EntryState.Occupied) continue;
            usize idx = self.hash_fn(self.keys[i]) & mask;
            for (usize j = 0; j < new_cap; j++) {
                usize slot = (idx + j) & mask;
                if (new_states[slot] == EntryState.Empty) {
                    new_keys[slot]   = self.keys[i];
                    new_vals[slot]   = self.vals[i];
                    new_states[slot] = EntryState.Occupied;
                    break;
                }
            }
        }

        free(self.keys);
        free(self.vals);
        free(self.states);
        self.keys       = new_keys;
        self.vals       = new_vals;
        self.states     = new_states;
        self.cap        = new_cap;
        self.tombstones = 0;
    }
};
