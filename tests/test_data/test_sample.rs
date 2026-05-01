// Regular function
fn add(x: i32, y: i32) -> i32 {
    x + y
}

// Public function
pub fn greet(name: &str) -> String {
    format!("Hello, {}!", name)
}

// Async function
async fn fetch_data(url: &str) -> Result<String, Error> {
    let response = reqwest::get(url).await?;
    Ok(response.text().await?)
}

// Unsafe function
unsafe fn dereference(ptr: *const i32) -> i32 {
    *ptr
}

// Generic function
fn first<T: PartialOrd>(list: &[T]) -> &T {
    &list[0]
}

// Const function
const fn add_const(a: usize, b: usize) -> usize {
    a + b
}

// Extern function
extern "C" fn callback(data: *mut std::ffi::c_void) {
    println!("callback invoked");
}

// Multiple modifiers
pub unsafe async fn complex_op(handle: u64) -> Result<(), Error> {
    // complex operation
    Ok(())
}

// Struct with impl
struct Service {
    name: String,
}

impl Service {
    pub fn new(name: &str) -> Self {
        Service { name: name.to_string() }
    }

    pub async fn run(&self) -> Result<(), Error> {
        Ok(())
    }
}

// Trait
pub trait Repository<T> {
    fn find(&self, id: &str) -> Option<&T>;
    fn save(&mut self, item: T);
}
