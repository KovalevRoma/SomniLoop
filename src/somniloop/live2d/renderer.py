"""Own a real Cubism Native model and isolated Qt/OpenGL render target."""

import ctypes as ct
import sys

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

from .resources import installation_root


def render_size(width: int, height: int, dpr: float) -> QSize:
    """Supersample edges without allowing unbounded GPU/readback allocations."""
    ratio = min(max(1.0, dpr) * 2.0, 1536 / max(1, width, height))
    return QSize(max(1, round(width * ratio)), max(1, round(height * ratio)))


class NativeRenderer:
    def __init__(self, resources):
        self.context = self.surface = self.fbo = self.handle = None
        self.readback_fbo = None
        suffix = "dylib" if sys.platform == "darwin" else "so"
        self.lib = ct.CDLL(str(installation_root() / f"build/libsomniloop_live2d.{suffix}"))
        signatures = {
            "sl_error": (ct.c_char_p, []),
            "sl_create": (ct.c_void_p, [ct.c_char_p, ct.c_char_p]),
            "sl_texture": (ct.c_int, [ct.c_void_p, ct.c_int, ct.c_int, ct.c_int, ct.c_void_p]),
            "sl_draw": (ct.c_int, [ct.c_void_p, ct.c_float, ct.c_int, ct.c_int, ct.c_float]),
            "sl_motion": (ct.c_int, [ct.c_void_p, ct.c_char_p, ct.c_int]),
            "sl_expression": (ct.c_int, [ct.c_void_p, ct.c_char_p]),
            "sl_parameter": (ct.c_int, [ct.c_void_p, ct.c_char_p, ct.c_float]),
            "sl_get_parameter": (ct.c_int, [ct.c_void_p, ct.c_char_p, ct.POINTER(ct.c_float)]),
            "sl_part_bounds": (ct.c_int, [ct.c_void_p, ct.c_char_p, ct.c_int, ct.c_int,
                                         ct.POINTER(ct.c_float)]),
            "sl_look": (None, [ct.c_void_p, ct.c_float, ct.c_float]),
            "sl_idle": (None, [ct.c_void_p, ct.c_int]),
            "sl_motion_group": (ct.c_char_p, [ct.c_void_p]),
            "sl_destroy": (None, [ct.c_void_p]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, args
        try:
            fmt = QSurfaceFormat()
            fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
            fmt.setVersion(2, 1)
            fmt.setAlphaBufferSize(8)
            fmt.setDepthBufferSize(24)
            fmt.setStencilBufferSize(8)
            self.surface = QOffscreenSurface()
            self.surface.setFormat(fmt)
            self.surface.create()
            self.context = QOpenGLContext()
            self.context.setFormat(fmt)
            if not self.surface.isValid() or not self.context.create():
                raise RuntimeError("Cannot create a desktop OpenGL context for Live2D")
            self.current()
            shaders = (
                installation_root()
                / "sdk/CubismSdkForNative-5-r.4.1/Framework/src/Rendering/OpenGL/Shaders/Standard"
            )
            if not shaders.is_dir():
                raise FileNotFoundError("Cubism OpenGL shaders are missing; rerun Live2D setup")
            self.handle = self.lib.sl_create(
                str(resources.manifest).encode(), str(shaders).encode()
            )
            self.check(self.handle)
            for index, path in enumerate(resources.textures):
                texture = QImage(str(path))
                if texture.isNull():
                    raise ValueError(f"Cannot decode Live2D texture: {path.name}")
                texture = texture.convertToFormat(QImage.Format.Format_RGBA8888)
                pixels = ct.create_string_buffer(bytes(texture.constBits()))
                self.check(
                    self.lib.sl_texture(
                        self.handle, index, texture.width(), texture.height(), pixels
                    )
                )
            self.context.doneCurrent()
        except Exception:
            self.close()
            raise

    def current(self):
        if not self.context.makeCurrent(self.surface):
            raise RuntimeError("Live2D OpenGL context is unavailable")

    def check(self, result):
        if not result:
            message = self.lib.sl_error()
            raise RuntimeError(message.decode(errors="replace") if message else "Live2D failed")

    def frame(self, size: QSize, dt: float, opacity: float,
              output_size: QSize | None = None) -> QImage:
        self.current()
        try:
            if self.fbo is None or self.fbo.size() != size:
                self.fbo = None
                fmt = QOpenGLFramebufferObjectFormat()
                fmt.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
                self.fbo = QOpenGLFramebufferObject(size, fmt)
                if not self.fbo.isValid():
                    raise RuntimeError("Cannot allocate the Live2D render buffer")
            if not self.fbo.bind():
                raise RuntimeError("Cannot bind the Live2D render buffer")
            self.check(self.lib.sl_draw(self.handle, dt, size.width(), size.height(), opacity))
            source = self.fbo
            if (output_size is not None and output_size != size
                    and QOpenGLFramebufferObject.hasOpenGLFramebufferBlit()):
                if (self.readback_fbo is None or self.readback_fbo.size() != output_size):
                    self.readback_fbo = QOpenGLFramebufferObject(output_size)
                    if not self.readback_fbo.isValid():
                        raise RuntimeError("Cannot allocate the Live2D readback buffer")
                # Resolve supersampling on the GPU before transferring pixels to Qt.
                QOpenGLFramebufferObject.blitFramebuffer(
                    self.readback_fbo, QRect(0, 0, output_size.width(), output_size.height()),
                    self.fbo, QRect(0, 0, size.width(), size.height()),
                    0x00004000, 0x2601,  # GL_COLOR_BUFFER_BIT, GL_LINEAR
                )
                source = self.readback_fbo
            # Old OpenGL implementations retain the original full-resolution path.
            image = source.toImage()
            self.fbo.release()
            return image
        finally:
            self.context.doneCurrent()

    def parameter(self, name):
        value = ct.c_float()
        self.check(self.lib.sl_get_parameter(self.handle, name.encode(), ct.byref(value)))
        return value.value

    def part_bounds(self, name, width, height):
        bounds = (ct.c_float * 4)()
        if self.lib.sl_part_bounds(self.handle, name.encode(), width, height, bounds):
            return tuple(bounds)
        return None

    def close(self):
        if self.context and self.surface and self.context.makeCurrent(self.surface):
            if self.handle:
                self.lib.sl_destroy(self.handle)
                self.handle = None
            self.fbo = None
            self.readback_fbo = None
            self.context.doneCurrent()
        self.context = None
        if self.surface:
            self.surface.destroy()
            self.surface = None
