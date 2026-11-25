import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
import os
import io
import base64
from typing import Optional

def generate_qr_code_image(
    data_url: str,
    output_path: Optional[str] = None,
    dark_color: tuple = (0, 0, 0),
    light_color: tuple = (255, 255, 255)
) -> str:
    """
    Generate an Apple-aesthetic QR code with rounded modules.
    Returns relative web path or base64 data URI.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(data_url)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        color_mask=SolidFillColorMask(front_color=dark_color, back_color=light_color)
    )

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path)
        return output_path
    else:
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
