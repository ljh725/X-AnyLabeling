import base64
import json
import os
import os.path as osp
import tempfile
import time

import PIL.Image
from PIL import ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

from . import utils
from .label_converter import LabelConverter
from .logger import logger
from .schema import XLABEL_BASIC_FIELDS, create_xlabel_template
from .shape import Shape
from .shape_identity import (
    MISSING_SHAPE_ID,
    SHAPE_ID_FIELD,
    describe_shape_identity_diagnostics,
    normalize_shape_identities,
    validate_shape_identities,
)

PIL.Image.MAX_IMAGE_PIXELS = None

PERF_LOG_ENABLED = os.getenv("XANYLABELING_PERF_LOG") == "1"


def _perf_log(message, *args):
    """Emit performance logs only when enabled by env var."""
    if PERF_LOG_ENABLED:
        logger.info(message, *args)


class LabelFileError(Exception):
    pass


class LabelFile:
    suffix = ".json"

    def __init__(self, filename=None, image_dir=None):
        self.shapes = []
        self.shape_identity_diagnostics = ()
        self.image_path = None
        self.image_data = None
        self.image_dir = image_dir
        if filename is not None:
            self.load(filename)
        self.filename = filename

    @staticmethod
    def _check_image_height_and_width(image_data, image_height, image_width):
        img_arr = utils.img_b64_to_arr(image_data)
        if image_height is not None and img_arr.shape[0] != image_height:
            logger.error(
                "image_height does not match with image_data or image_path, "
                "so getting image_height from actual image."
            )
            image_height = img_arr.shape[0]
        if image_width is not None and img_arr.shape[1] != image_width:
            logger.error(
                "image_width does not match with image_data or image_path, "
                "so getting image_width from actual image."
            )
            image_width = img_arr.shape[1]
        return image_height, image_width

    @staticmethod
    def is_label_file(filename):
        return osp.splitext(filename)[1].lower() == LabelFile.suffix

    @staticmethod
    def load_image_file(filename, default=None):
        _t0 = time.perf_counter()
        try:
            with open(filename, "rb") as f:
                data = f.read()
            elapsed = time.perf_counter() - _t0
            if elapsed > 0.05:
                _perf_log(
                    "LabelFile.load_image_file slow: %.3fs, file=%s",
                    elapsed,
                    filename,
                )
            return data
        except Exception:
            logger.error(f"Failed opening image file: {filename}")
            return default

    def load(self, filename):
        _t0 = time.perf_counter()
        try:
            with utils.io_open(filename, "r") as f:
                data = json.load(f)
            _t_json = time.perf_counter()

            if data.get("version") is None:
                logger.warning(
                    f"Loading JSON file ({filename}) of unknown version"
                )

            if data["shapes"]:
                for i in range(len(data["shapes"])):
                    shape_points = data["shapes"][i]["points"]
                    if (
                        data["shapes"][i]["shape_type"] == "rectangle"
                        and len(shape_points) == 2
                    ):
                        logger.warning(
                            "UserWarning: Diagonal vertex mode is deprecated in X-AnyLabeling release v2.2.0 or later.\n"
                            "Please update your code to accommodate the new four-point mode."
                        )
                        data["shapes"][i]["points"] = (
                            utils.rectangle_from_diagonal(shape_points)
                        )

            data["imagePath"] = osp.basename(data["imagePath"])
            if data.get("imageData") is not None:
                _t_image = time.perf_counter()
                image_data = base64.b64decode(data["imageData"])
                _perf_log(
                    "LabelFile.load imageData decode: %.3fs, file=%s",
                    time.perf_counter() - _t_image,
                    filename,
                )
            else:
                # relative path from label file to relative path from cwd
                if self.image_dir:
                    image_path = osp.join(self.image_dir, data["imagePath"])
                else:
                    image_path = osp.join(
                        osp.dirname(filename), data["imagePath"]
                    )
                _t_image = time.perf_counter()
                image_data = self.load_image_file(image_path)
                _perf_log(
                    "LabelFile.load image bytes: %.3fs, file=%s",
                    time.perf_counter() - _t_image,
                    image_path,
                )

            flags = data.get("flags", {})
            image_path = data["imagePath"]

            if image_data is not None:
                self._check_image_height_and_width(
                    base64.b64encode(image_data).decode("utf-8"),
                    data.get("imageHeight"),
                    data.get("imageWidth"),
                )

            _t_shape_build = time.perf_counter()
            identity_result = normalize_shape_identities(
                (
                    shape.get(SHAPE_ID_FIELD, MISSING_SHAPE_ID)
                    for shape in data["shapes"]
                )
            )
            shapes = []
            for raw_shape, shape_id in zip(
                data["shapes"], identity_result.identities
            ):
                normalized_shape = dict(raw_shape)
                normalized_shape[SHAPE_ID_FIELD] = shape_id
                shapes.append(Shape().load_from_dict(normalized_shape))
            if identity_result.diagnostics:
                logger.warning(
                    "Repaired %d Shape identities while loading %s: %s",
                    identity_result.repaired_count,
                    filename,
                    describe_shape_identity_diagnostics(
                        identity_result.diagnostics
                    ),
                )
            _t_shapes = time.perf_counter()
            total_time = _t_shapes - _t0
            if total_time > 0.1:
                _perf_log(
                    "LabelFile.load slow: json=%.3fs, pre_shapes=%.3fs, "
                    "shape_build=%.3fs, total=%.3fs, file=%s",
                    _t_json - _t0,
                    _t_shape_build - _t_json,
                    _t_shapes - _t_shape_build,
                    total_time,
                    filename,
                )

        except Exception as e:  # noqa
            raise LabelFileError(e) from e

        other_data = {}
        for key, value in data.items():
            if key not in XLABEL_BASIC_FIELDS:
                other_data[key] = value

        # Add new fields if not available
        other_data["description"] = other_data.get("description", "")
        other_data["checked"] = data.get("checked", False) is True

        # Only replace data after everything is loaded.
        self.flags = flags
        self.shapes = shapes
        self.shape_identity_diagnostics = identity_result.diagnostics
        self.image_path = image_path
        self.image_data = image_data
        self.filename = filename
        self.other_data = other_data

    def save(
        self,
        filename=None,
        shapes=None,
        image_path=None,
        image_height=None,
        image_width=None,
        image_data=None,
        other_data=None,
        flags=None,
    ):
        identity_violations = validate_shape_identities(
            (
                (
                    shape.get(SHAPE_ID_FIELD, MISSING_SHAPE_ID)
                    if isinstance(shape, dict)
                    else MISSING_SHAPE_ID
                )
                for shape in shapes
            )
        )
        if identity_violations:
            raise LabelFileError(
                "Invalid Shape identities: "
                + describe_shape_identity_diagnostics(identity_violations)
            )
        if image_data is not None:
            image_data = base64.b64encode(image_data).decode("utf-8")
            image_height, image_width = self._check_image_height_and_width(
                image_data, image_height, image_width
            )

        if other_data is None:
            other_data = {}
        if flags is None:
            flags = {}
        checked = other_data.get("checked", False) is True
        for i, shape in enumerate(shapes):
            if shape["shape_type"] == "rectangle":
                sorted_box = LabelConverter.calculate_bounding_box(
                    shape["points"]
                )
                xmin, ymin, xmax, ymax = sorted_box
                shape["points"] = [
                    [xmin, ymin],
                    [xmax, ymin],
                    [xmax, ymax],
                    [xmin, ymax],
                ]
                shapes[i] = shape

        data = create_xlabel_template(
            flags=flags,
            checked=checked,
            shapes=shapes,
            image_path=image_path,
            image_data=image_data,
            image_height=image_height,
            image_width=image_width,
        )

        for key, value in other_data.items():
            if key == "checked":
                continue
            assert key not in data
            data[key] = value
        temporary_path = None
        try:
            target_dir = osp.dirname(osp.abspath(filename))
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=f".{osp.basename(filename)}.",
                suffix=".tmp",
                dir=target_dir,
                text=True,
            )
            with os.fdopen(
                file_descriptor, "w", encoding="utf-8", newline=""
            ) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, filename)
            temporary_path = None
            self.filename = filename
        except Exception as e:  # noqa
            raise LabelFileError(e) from e
        finally:
            if temporary_path and osp.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass
