package main

import "fmt"

// Regular function
func add(x int, y int) int {
    return x + y
}

// Generic function
func Map[T any, U any](items []T, fn func(T) U) []U {
    result := make([]U, len(items))
    for i, item := range items {
        result[i] = fn(item)
    }
    return result
}

// Method with receiver
func (s *Store) Get(id string) (Item, error) {
    return s.data[id], nil
}

// Generic method
func (s *Store) Find[T any](id string) (T, error) {
    var zero T
    return zero, nil
}

// Multiple return values
func divide(a, b float64) (float64, error) {
    if b == 0 {
        return 0, fmt.Errorf("division by zero")
    }
    return a / b, nil
}
