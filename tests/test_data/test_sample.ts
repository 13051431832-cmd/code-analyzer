// Typed function
function greet(name: string): string {
    return `Hello ${name}`;
}

// Multiple modifiers
export function exportedFn(input: number): number {
    return input * 2;
}

// Arrow function with generics
const identity = <T>(arg: T): T => arg;

// Generic function
function firstElement<T>(arr: T[]): T | undefined {
    return arr[0];
}

// Class with modifiers
class Service {
    private value: number = 0;

    constructor(init: number) {
        this.value = init;
    }

    // Multi-modifier method
    public static getInstance(): Service {
        return new Service(0);
    }

    // Public method with generic
    public async fetch<T>(url: string): Promise<T> {
        const response = await fetch(url);
        return response.json() as T;
    }

    // Getter
    get currentValue(): number {
        return this.value;
    }

    // Setter
    set currentValue(val: number) {
        this.value = val;
    }

    // Readonly modifier
    public readonly getCount(): number {
        return this.value;
    }
}

// Abstract class
abstract class BaseRepository<T> {
    abstract find(id: string): Promise<T | null>;
    abstract save(entity: T): Promise<void>;

    public count(): number {
        return 0;
    }
}
