//! Scheduling policy only: deterministic round robin over a bounded table.
use super::{READY, Task};
pub fn next(tasks: &[Task; 2], previous: usize) -> Option<usize> {
    (1..=2)
        .map(|offset| (previous + offset) % 2)
        .find(|&index| tasks[index].state == READY)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn skips_dead_tasks_and_reaches_idle() {
        let mut tasks = [Task::EMPTY; 2];
        assert_eq!(next(&tasks, 0), Some(1));
        tasks[1].state = super::super::FAULTED;
        assert_eq!(next(&tasks, 0), Some(0));
        tasks[0].state = super::super::EXITED;
        assert_eq!(next(&tasks, 1), None);
    }
}
