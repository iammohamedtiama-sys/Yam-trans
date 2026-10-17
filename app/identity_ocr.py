"""Local OCR adapter; documents never leave the company's server."""
import base64
import io
import re
import subprocess
import tempfile
from pathlib import Path
from fastapi import HTTPException


def decode_image(data):
    if not data or not isinstance(data,str) or len(data)>7_000_000:
        raise HTTPException(422,'Photo manquante ou trop volumineuse (5 Mo maximum)')
    try:
        header,encoded=data.split(',',1)
        if header not in {'data:image/jpeg;base64','data:image/png;base64','data:image/webp;base64'}:
            raise ValueError()
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)>5_000_000:raise ValueError()
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            if image.width*image.height>12_000_000:raise ValueError()
            image.verify()
        return raw
    except Exception as exc:
        if isinstance(exc,HTTPException):raise
        raise HTTPException(422,'Photo invalide ou dimensions excessives') from None


def recognize(data):
    raw=decode_image(data)
    try:
        with tempfile.TemporaryDirectory(prefix='yam-ocr-') as directory:
            path=Path(directory)/'document-image'
            path.write_bytes(raw)
            result=subprocess.run(['tesseract',str(path),'stdout','-l','eng','--psm','11'],capture_output=True,timeout=25,check=True)
        text=result.stdout.decode('utf-8',errors='replace')[:12000]
        # Suggest candidates; do not infer nationality, document type or fixed prefixes.
        candidates=list(dict.fromkeys(re.findall(r'\b(?=[A-Z0-9-]{4,30}\b)(?=[A-Z0-9-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)*\b',text.upper())))[:30]
        return {'text':text,'candidates':candidates,'requiresConfirmation':True}
    except FileNotFoundError:
        raise HTTPException(503,'Le moteur OCR n’est pas installé sur ce serveur') from None
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
        raise HTTPException(422,'Lecture impossible. Reprenez une photo nette ou saisissez la pièce manuellement.') from None
