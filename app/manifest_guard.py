"""An arrival confirmation seals the manifest, not the subsequent parcel delivery."""

def manifest_locked(payload):
    return bool((payload or {}).get('arrivedAt'))


def manifest_content(payload):
    return {key: value for key, value in (payload or {}).items()
            if not key.startswith('_') and key != 'updatedAt'}


LOCK_MESSAGE = 'Arrivée confirmée : ce bordereau ne peut plus être modifié.'
