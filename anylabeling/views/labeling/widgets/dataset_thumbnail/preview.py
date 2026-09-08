"""Background-loaded crop and whole-image preview for one stable object."""

from dataclasses import replace

from PyQt6 import QtCore, QtGui, QtWidgets

from ...dataset_index.types import DatasetThumbnailRef
from .pipeline import ThumbnailRenderer, ThumbnailRenderResult
from .render_options import RenderOptions


class ThumbnailPreview(QtWidgets.QDialog):
    """Show one target without navigating the annotation window."""

    def __init__(
        self,
        ref: DatasetThumbnailRef,
        cache_root: str,
        options: RenderOptions,
        parent: QtWidgets.QWidget,
    ) -> None:
        """Start a nonblocking preview with its own cancellable renderer."""
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(self.tr("Object preview"))
        self.resize(1100, 800)
        self.ref, self.options = ref, options
        self._image = None
        self._closed = False
        root = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem(self.tr("Target crop"), "crop")
        self.mode.addItem(self.tr("Whole image with target"), "full")
        row.addWidget(self.mode)
        identity = QtWidgets.QLabel(
            f"{ref.image_path} · {ref.label} · {ref.shape_id}"
        )
        identity.setWordWrap(True)
        identity.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        row.addWidget(identity, 1)
        root.addLayout(row)
        self.picture = QtWidgets.QLabel(self.tr("Loading preview…"))
        self.picture.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumSize(160, 120)
        self.picture.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Ignored,
        )
        root.addWidget(self.picture, 1)
        self.renderer = ThumbnailRenderer(
            cache_root, max_concurrency=1, parent=self
        )
        self.renderer.result_ready.connect(self._result)
        self.mode.currentIndexChanged.connect(self.load_preview)
        self.space = QtGui.QShortcut(QtGui.QKeySequence("Space"), self)
        self.space.activated.connect(self.close)
        self.finished.connect(self._stop)
        self.load_preview()

    def load_preview(self) -> None:
        """Request one large image and ignore results from earlier modes."""
        self._image = None
        self.picture.clear()
        self.picture.setText(self.tr("Loading preview…"))
        mode = self.mode.currentData()
        options = replace(
            self.options,
            mode=mode,
            show_box=self.options.show_box or mode == "full",
        )
        self.renderer.request([self.ref], size=(1800, 1400), options=options)

    def _result(self, result: ThumbnailRenderResult) -> None:
        """Display errors or the latest background result without blocking."""
        if self._closed or result.generation != self.renderer.generation:
            return
        if result.error:
            self.picture.setText(
                self.tr("Preview unavailable: %1").replace("%1", result.error)
            )
            return
        self._image = result.image
        self._paint_image()

    def _paint_image(self) -> None:
        """Fit the preview while preserving the source aspect ratio."""
        if self._image is not None:
            self.picture.setPixmap(
                QtGui.QPixmap.fromImage(self._image).scaled(
                    self.picture.size(),
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
            )

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """Resize the existing preview without decoding the source again."""
        super().resizeEvent(event)
        self._paint_image()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Cancel obsolete work and release the dialog without joining it."""
        self._stop()
        super().closeEvent(event)

    def _stop(self) -> None:
        """Stop workers for both window close and Escape rejection."""
        if not self._closed:
            self._closed = True
            self.renderer.close()
