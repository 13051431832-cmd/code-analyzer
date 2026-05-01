// Regular function
function foo(x, y) {
    return x + y;
}

// Async function
async function fetchData(url) {
    const response = await fetch(url);
    return response.json();
}

// Generator function
function* generatorFunc() {
    yield 1;
    yield 2;
}

// Arrow function
const baz = () => {
    console.log("hello");
};

// Arrow function with body on next line
const arrowMulti = () =>
{
    return 42;
};

// Default export function
export default function bar() {
    return 42;
}

// Default export anonymous
export default function() {
    return 0;
}

// Named export function
export function exportedFunc(input) {
    return input * 2;
}

// Class with methods
class MyClass {
    constructor(value) {
        this.value = value;
    }

    // Regular method
    getName() {
        return "MyClass";
    }

    // Static method
    static getClassName() {
        return "MyClass";
    }

    // Async method
    async process(data) {
        return await this._transform(data);
    }
}

// Object method shorthand
const obj = {
    method1() {
        return 1;
    }
};
