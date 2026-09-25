use pyo3::prelude::*;
use pyo3::types::PyType;
use windows::Win32::Foundation::HWND;
use winvd::{self, Desktop};

#[pyclass]
#[derive(Clone)]
pub struct VirtualDesktop {
    #[pyo3(get)]
    pub number: u32, // 1-based (pyvda / Caster convention)
    #[pyo3(get)]
    pub index: u32,  // 0-based (Windows / VDA convention)
    desktop: Desktop,
}

#[pymethods]
impl VirtualDesktop {
    #[new]
    #[pyo3(signature = (number=None, current=false))]
    pub fn new(number: Option<u32>, current: Option<bool>) -> PyResult<Self> {
        if current.unwrap_or(false) {
            let desk = winvd::get_current_desktop()
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
            let idx = desk
                .get_index()
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
            Ok(VirtualDesktop {
                number: idx + 1,
                index: idx,
                desktop: desk,
            })
        } else if let Some(n) = number {
            if n == 0 {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "Desktop number must be 1-based (n >= 1).",
                ));
            }
            let idx = n - 1;
            let desk = winvd::get_desktop(idx);
            Ok(VirtualDesktop {
                number: n,
                index: idx,
                desktop: desk,
            })
        } else {
            Err(pyo3::exceptions::PyValueError::new_err(
                "Must provide desktop number (>= 1) or current=True",
            ))
        }
    }

    #[classmethod]
    pub fn current(_cls: &Bound<'_, PyType>) -> PyResult<Self> {
        let desk = winvd::get_current_desktop()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
        let idx = desk
            .get_index()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
        Ok(VirtualDesktop {
            number: idx + 1,
            index: idx,
            desktop: desk,
        })
    }

    #[classmethod]
    pub fn create(_cls: &Bound<'_, PyType>) -> PyResult<Self> {
        let desk = winvd::create_desktop()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
        let idx = desk
            .get_index()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
        Ok(VirtualDesktop {
            number: idx + 1,
            index: idx,
            desktop: desk,
        })
    }

    #[getter]
    pub fn id(&self) -> PyResult<String> {
        let guid = self
            .desktop
            .get_id()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
        Ok(format!("{:?}", guid))
    }

    #[getter]
    pub fn name(&self) -> PyResult<String> {
        self.desktop
            .get_name()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
    }

    pub fn set_name(&self, name: &str) -> PyResult<()> {
        self.desktop
            .set_name(name)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
    }

    pub fn go(&self) -> PyResult<()> {
        winvd::switch_desktop(self.index)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
    }

    pub fn switch(&self) -> PyResult<()> {
        self.go()
    }

    #[pyo3(signature = (fallback=None))]
    pub fn remove(&self, fallback: Option<&VirtualDesktop>) -> PyResult<()> {
        let fb_idx = fallback.map(|f| f.index).unwrap_or(0);
        winvd::remove_desktop(self.index, fb_idx)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
    }

    fn __repr__(&self) -> String {
        format!("<VirtualDesktop number={} (index={})>", self.number, self.index)
    }

    fn __eq__(&self, other: &VirtualDesktop) -> bool {
        self.index == other.index
    }
}

#[pyclass]
#[derive(Clone)]
pub struct AppView {
    #[pyo3(get)]
    pub hwnd: usize,
}

#[pymethods]
impl AppView {
    #[new]
    pub fn new(hwnd: usize) -> Self {
        AppView { hwnd }
    }

    pub fn move_to(&self, desktop: &VirtualDesktop) -> PyResult<()> {
        let hwnd = HWND(self.hwnd as _);
        winvd::move_window_to_desktop(desktop.index, &hwnd)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
    }

    pub fn r#move(&self, desktop: &VirtualDesktop) -> PyResult<()> {
        self.move_to(desktop)
    }

    pub fn is_pinned(&self) -> PyResult<bool> {
        let hwnd = HWND(self.hwnd as _);
        match winvd::is_pinned_window(hwnd) {
            Ok(v) => Ok(v),
            Err(winvd::Error::WindowNotFound) => Ok(false),
            Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e))),
        }
    }

    pub fn pin(&self) -> PyResult<()> {
        let hwnd = HWND(self.hwnd as _);
        winvd::pin_window(hwnd)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
    }

    pub fn unpin(&self) -> PyResult<()> {
        let hwnd = HWND(self.hwnd as _);
        winvd::unpin_window(hwnd)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
    }

    pub fn is_app_pinned(&self) -> PyResult<bool> {
        let hwnd = HWND(self.hwnd as _);
        match winvd::is_pinned_app(hwnd) {
            Ok(v) => Ok(v),
            Err(winvd::Error::WindowNotFound) => Ok(false),
            Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e))),
        }
    }

    pub fn pin_app(&self) -> PyResult<()> {
        let hwnd = HWND(self.hwnd as _);
        winvd::pin_app(hwnd)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
    }

    pub fn unpin_app(&self) -> PyResult<()> {
        let hwnd = HWND(self.hwnd as _);
        winvd::unpin_app(hwnd)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
    }

    pub fn is_on_desktop(&self, desktop: &VirtualDesktop) -> PyResult<bool> {
        let hwnd = HWND(self.hwnd as _);
        match winvd::is_window_on_desktop(desktop.index, hwnd) {
            Ok(v) => Ok(v),
            Err(winvd::Error::WindowNotFound) => Ok(false),
            Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e))),
        }
    }

    pub fn is_on_current_desktop(&self) -> PyResult<bool> {
        let hwnd = HWND(self.hwnd as _);
        match winvd::is_window_on_current_desktop(hwnd) {
            Ok(v) => Ok(v),
            Err(winvd::Error::WindowNotFound) => Ok(false),
            Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e))),
        }
    }

    fn __repr__(&self) -> String {
        format!("<AppView hwnd={:#x}>", self.hwnd)
    }

    fn __eq__(&self, other: &AppView) -> bool {
        self.hwnd == other.hwnd
    }
}

#[pyfunction]
pub fn get_virtual_desktops() -> PyResult<Vec<VirtualDesktop>> {
    let desktops = winvd::get_desktops()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
    let mut result = Vec::new();
    for (i, desk) in desktops.into_iter().enumerate() {
        result.push(VirtualDesktop {
            number: (i + 1) as u32,
            index: i as u32,
            desktop: desk,
        });
    }
    Ok(result)
}

#[pyfunction]
pub fn go_to_desktop_number(number: u32) -> PyResult<()> {
    let index = if number > 0 { number - 1 } else { 0 };
    winvd::switch_desktop(index)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
}

#[pyfunction]
pub fn switch_desktop(index: u32) -> PyResult<()> {
    winvd::switch_desktop(index)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
}

#[pyfunction]
pub fn get_desktop_count() -> PyResult<u32> {
    winvd::get_desktop_count()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
}

#[pyfunction]
pub fn get_current_desktop_number() -> PyResult<u32> {
    let desk = winvd::get_current_desktop()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
    let idx = desk
        .get_index()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))?;
    Ok(idx + 1)
}

#[pyfunction]
pub fn move_window_to_desktop(hwnd: usize, number: u32) -> PyResult<()> {
    let hwnd = HWND(hwnd as _);
    let index = if number > 0 { number - 1 } else { 0 };
    winvd::move_window_to_desktop(index, &hwnd)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
}

#[pyfunction]
pub fn pin_window(hwnd: usize) -> PyResult<()> {
    let hwnd = HWND(hwnd as _);
    winvd::pin_window(hwnd)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
}

#[pyfunction]
pub fn unpin_window(hwnd: usize) -> PyResult<()> {
    let hwnd = HWND(hwnd as _);
    winvd::unpin_window(hwnd)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
}

#[pyfunction]
pub fn is_pinned_window(hwnd: usize) -> PyResult<bool> {
    let hwnd = HWND(hwnd as _);
    match winvd::is_pinned_window(hwnd) {
        Ok(v) => Ok(v),
        Err(winvd::Error::WindowNotFound) => Ok(false),
        Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e))),
    }
}

#[pyfunction]
pub fn pin_app(hwnd: usize) -> PyResult<()> {
    let hwnd = HWND(hwnd as _);
    winvd::pin_app(hwnd)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
}

#[pyfunction]
pub fn unpin_app(hwnd: usize) -> PyResult<()> {
    let hwnd = HWND(hwnd as _);
    winvd::unpin_app(hwnd)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
}

#[pyfunction]
pub fn is_pinned_app(hwnd: usize) -> PyResult<bool> {
    let hwnd = HWND(hwnd as _);
    match winvd::is_pinned_app(hwnd) {
        Ok(v) => Ok(v),
        Err(winvd::Error::WindowNotFound) => Ok(false),
        Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e))),
    }
}

#[pyfunction]
pub fn sync_pinned_apps() -> PyResult<u32> {
    winvd::sync_pinned_apps()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{:?}", e)))
}

#[pymodule]
fn virtualdesktopaccessor(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<VirtualDesktop>()?;
    m.add_class::<AppView>()?;
    m.add_function(wrap_pyfunction!(get_virtual_desktops, m)?)?;
    m.add_function(wrap_pyfunction!(go_to_desktop_number, m)?)?;
    m.add_function(wrap_pyfunction!(switch_desktop, m)?)?;
    m.add_function(wrap_pyfunction!(get_desktop_count, m)?)?;
    m.add_function(wrap_pyfunction!(get_current_desktop_number, m)?)?;
    m.add_function(wrap_pyfunction!(move_window_to_desktop, m)?)?;
    m.add_function(wrap_pyfunction!(pin_window, m)?)?;
    m.add_function(wrap_pyfunction!(unpin_window, m)?)?;
    m.add_function(wrap_pyfunction!(is_pinned_window, m)?)?;
    m.add_function(wrap_pyfunction!(pin_app, m)?)?;
    m.add_function(wrap_pyfunction!(unpin_app, m)?)?;
    m.add_function(wrap_pyfunction!(is_pinned_app, m)?)?;
    m.add_function(wrap_pyfunction!(sync_pinned_apps, m)?)?;
    Ok(())
}
