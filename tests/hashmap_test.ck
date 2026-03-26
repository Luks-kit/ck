$include "stdio.h";
$import "std/hashmap.ck";

fn main() -> i32 {
    auto m = hashmap(String, i32).new(hash_string, eq_string);

    m.insert(String.from("apple"),  1);
    m.insert(String.from("banana"), 2);
    m.insert(String.from("cherry"), 3);
    printf("count = %zu\n", m.count());

    // lookup by temporary String
    auto r = m.get(String.lit("banana"));
    $tag switch (r) {
        case (Result.ok v):  { printf("banana = %d\n", v); }
        case (Result.err e): { printf("err: %s\n", e); }
    }

    // update
    m.insert(String.from("banana"), 22);
    auto r2 = m.get(String.lit("banana"));
    $tag switch (r2) {
        case (Result.ok v):  { printf("banana updated = %d\n", v); }
        case (Result.err e): { printf("err: %s\n", e); }
    }

    // remove
    m.remove(String.lit("apple"));
    printf("has apple: %d\n",  m.contains(String.lit("apple")));
    printf("has cherry: %d\n", m.contains(String.lit("cherry")));
    printf("count after remove = %zu\n", m.count());

    // not found
    auto r3 = m.get(String.lit("mango"));
    $tag switch (r3) {
        case (Result.ok v):  { printf("unexpected: %d\n", v); }
        case (Result.err e): { printf("not found: %s\n", e); }
    }

    return 0;
}
