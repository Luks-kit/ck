$import "std/string.ck";

$tag union Literal {
    i64 integer;
    u64 uinteger;
    f64 floating;
    char character;
    String str;

    fn $init integer(i64 i) -> Self { 
        return {.tag_ = Literal_integer_, .integer = i}; 
    }
    fn $init uinteger(u64 u) -> Self {
        return { .tag_ = Literal_uinteger_, .uinteger = u};
    }
    fn $init floating(f64 f) -> Self {
        return { .tag_ = Literal_floating_, .floating = f};
    }
    fn $init character(char c) -> Self {
        return { .tag_ = Literal_character_, .character = c};
    }
    fn $init str(String s) -> Self {
        return { .tag_ = Literal_str_, .str = s.clone()};
    }
    
    fn $dinit delete() -> void {
        if (self.tag_ == Literal_str_) $dinit(self.str);
    }

    fn clone() -> Literal {
        if(self.tag_ == Literal_str_) return {.tag_ = self.tag_, .str = self.str.clone()};
        else return *self;
    }

};
