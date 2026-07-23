//! Fixed-capacity ring buffer for tick storage.
//!
//! Provides a bounded, overwrite-on-overflow buffer for storing
//! recent ticks. Useful for maintaining a sliding window of
//! recent market data without unbounded memory growth.

/// A fixed-capacity ring buffer that stores elements in a circular fashion.
///
/// When the buffer is full, new elements overwrite the oldest.
#[derive(Debug, Clone)]
pub struct RingBuffer<T> {
    /// Internal storage.
    buffer: Vec<Option<T>>,
    /// Maximum capacity.
    capacity: usize,
    /// Index where the next element will be written.
    write_pos: usize,
    /// Number of elements currently stored.
    count: usize,
}

impl<T: Clone> RingBuffer<T> {
    /// Create a new ring buffer with the given capacity.
    ///
    /// # Panics
    /// Panics if capacity is 0.
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0, "RingBuffer capacity must be > 0");
        let mut buffer = Vec::with_capacity(capacity);
        buffer.resize_with(capacity, || None);
        Self {
            buffer,
            capacity,
            write_pos: 0,
            count: 0,
        }
    }

    /// Push an element into the buffer.
    ///
    /// If the buffer is full, the oldest element is overwritten.
    pub fn push(&mut self, item: T) {
        self.buffer[self.write_pos] = Some(item);
        self.write_pos = (self.write_pos + 1) % self.capacity;
        if self.count < self.capacity {
            self.count += 1;
        }
    }

    /// Get the number of elements currently in the buffer.
    pub fn len(&self) -> usize {
        self.count
    }

    /// Returns true if the buffer is empty.
    pub fn is_empty(&self) -> bool {
        self.count == 0
    }

    /// Returns true if the buffer is at full capacity.
    pub fn is_full(&self) -> bool {
        self.count == self.capacity
    }

    /// The maximum capacity of the buffer.
    pub fn capacity(&self) -> usize {
        self.capacity
    }

    /// Return all elements in order (oldest to newest).
    pub fn to_vec(&self) -> Vec<T> {
        if self.count == 0 {
            return Vec::new();
        }

        let start = if self.is_full() {
            self.write_pos
        } else {
            0
        };

        let mut result = Vec::with_capacity(self.count);
        for i in 0..self.count {
            let idx = (start + i) % self.capacity;
            if let Some(ref item) = self.buffer[idx] {
                result.push(item.clone());
            }
        }
        result
    }

    /// Get the most recently pushed element.
    pub fn latest(&self) -> Option<&T> {
        if self.count == 0 {
            return None;
        }
        let idx = (self.write_pos + self.capacity - 1) % self.capacity;
        self.buffer[idx].as_ref()
    }

    /// Get an element by index (0 = oldest, len-1 = newest).
    pub fn get(&self, index: usize) -> Option<&T> {
        if index >= self.count {
            return None;
        }
        let start = if self.is_full() {
            self.write_pos
        } else {
            0
        };
        let idx = (start + index) % self.capacity;
        self.buffer[idx].as_ref()
    }

    /// Clear all elements from the buffer.
    pub fn clear(&mut self) {
        for item in self.buffer.iter_mut() {
            *item = None;
        }
        self.write_pos = 0;
        self.count = 0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_push_and_read() {
        let mut rb = RingBuffer::new(3);
        rb.push(1);
        rb.push(2);
        rb.push(3);

        assert_eq!(rb.len(), 3);
        assert_eq!(rb.to_vec(), vec![1, 2, 3]);
    }

    #[test]
    fn test_overwrite_on_overflow() {
        let mut rb = RingBuffer::new(3);
        rb.push(1);
        rb.push(2);
        rb.push(3);
        rb.push(4); // overwrites 1

        assert_eq!(rb.len(), 3);
        assert_eq!(rb.to_vec(), vec![2, 3, 4]);
    }

    #[test]
    fn test_latest() {
        let mut rb = RingBuffer::new(5);
        rb.push(10);
        rb.push(20);
        assert_eq!(rb.latest(), Some(&20));
    }

    #[test]
    fn test_get_by_index() {
        let mut rb = RingBuffer::new(3);
        rb.push(10);
        rb.push(20);
        rb.push(30);

        assert_eq!(rb.get(0), Some(&10)); // oldest
        assert_eq!(rb.get(2), Some(&30)); // newest
        assert_eq!(rb.get(3), None); // out of bounds
    }

    #[test]
    fn test_clear() {
        let mut rb = RingBuffer::new(3);
        rb.push(1);
        rb.push(2);
        rb.clear();

        assert!(rb.is_empty());
        assert_eq!(rb.len(), 0);
    }

    #[test]
    fn test_is_full() {
        let mut rb = RingBuffer::new(2);
        assert!(!rb.is_full());
        rb.push(1);
        assert!(!rb.is_full());
        rb.push(2);
        assert!(rb.is_full());
    }
}
