#![no_std]
#![forbid(unsafe_code)]
//! Compile-only target layout probe. The object's read-only bytes are inspected,
//! never executed. No claimed ARM size comes from host pointer/layout assumptions.
use crosshair_ui::{
    Surface,
    components::{AppsScreen, Area, Event, InputQueue},
};

#[used]
pub static CROSSHAIR_UI_LAYOUT: [u32; 9] = [
    0x55493032,
    core::mem::size_of::<Surface<'static>>() as u32,
    core::mem::size_of::<AppsScreen>() as u32,
    core::mem::align_of::<AppsScreen>() as u32,
    core::mem::size_of::<InputQueue>() as u32,
    core::mem::size_of::<Event>() as u32,
    core::mem::size_of::<Area>() as u32,
    core::mem::size_of::<char>() as u32,
    core::mem::size_of::<usize>() as u32,
];
