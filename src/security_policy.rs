//! Pure copy-in policy shared by the ARM syscall handler and host tests.
pub const USER_DATA: u32 = 0x0100_1000;
pub const USER_END: u32 = USER_DATA + 4096;
pub const MAX_COPY: u32 = 64;
pub const EFAULT: u32 = (-14i32) as u32;
pub const EINVAL: u32 = (-22i32) as u32;
pub const ENOSYS: u32 = (-38i32) as u32;

/// Only the declared data page is an accepted copy-in source. Even zero-length
/// operations need an address in its closed [start,end] range. Cap checked first.
pub fn checked_copy(ptr: u32, len: u32) -> Result<usize, u32> {
    if len > MAX_COPY {
        return Err(EINVAL);
    }
    let end = ptr.checked_add(len).ok_or(EFAULT)?;
    if ptr < USER_DATA || end > USER_END {
        return Err(EFAULT);
    }
    Ok(len as usize)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn boundaries_overflow_and_zero_length_policy() {
        assert_eq!(checked_copy(USER_DATA, 64), Ok(64));
        assert_eq!(checked_copy(USER_END, 0), Ok(0));
        assert_eq!(checked_copy(USER_END - 1, 1), Ok(1));
        assert_eq!(checked_copy(USER_END - 4, 8), Err(EFAULT));
        assert_eq!(checked_copy(0, 0), Err(EFAULT));
        assert_eq!(checked_copy(u32::MAX - 15, 32), Err(EFAULT));
        assert_eq!(checked_copy(USER_DATA, 65), Err(EINVAL));
    }
    #[test]
    fn independent_wide_integer_oracle() {
        let mut seed = 0x9e37_79b9u32;
        for i in 0..100_000u32 {
            seed ^= seed << 13;
            seed ^= seed >> 17;
            seed ^= seed << 5;
            let ptr = if i % 2 == 0 {
                USER_DATA.wrapping_add(seed % 8192).wrapping_sub(2048)
            } else {
                seed
            };
            let len = if i % 3 == 0 {
                seed % 128
            } else {
                seed.rotate_left(11)
            };
            let expected = if len as u64 > 64 {
                Err(EINVAL)
            } else if ptr as u64 >= USER_DATA as u64 && ptr as u64 + len as u64 <= USER_END as u64 {
                Ok(len as usize)
            } else {
                Err(EFAULT)
            };
            assert_eq!(
                checked_copy(ptr, len),
                expected,
                "step {i}, ptr {ptr:x}, len {len}"
            );
        }
    }
}
