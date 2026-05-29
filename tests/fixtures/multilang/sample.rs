use std::fmt;

struct Town {
    name: String,
}

impl Town {
    fn new(name: String) -> Town {
        Town { name }
    }

    fn greet(&self) -> String {
        format!("Welcome to {}", self.name)
    }
}
