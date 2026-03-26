$import "std/string.ck";

$tag union Literal {
    i64 integer;
    u64 uinteger;
    f64 floating;
    bool boolean;
    char character;
    String str;
    
    fn $dinit delete() -> void {
       if(self.tag_ == Literal_str_){
           // ugly, but needed 
            String_drop(&self.str);
        } 
    }

    fn clone() -> Literal {
        if(self.tag_ == Literal_str_){
            String copy = self.str;
            return {.tag_ = self.tag_, .str = copy.clone()};
        } else return *self;
    }

};
