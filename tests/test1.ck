$import "std/io";

$template(type T)
struct Box {
    T value;
};

fn main() -> i32 {
    let x = 10;
    let y = 20.5;
    if (x < y) {
        printf("Hello World\n");
    }
    return 0;
}
