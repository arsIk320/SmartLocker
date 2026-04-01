from __future__ import annotations

from app.db.models import MaxGuestBindingModel
from app.modules.messenger_guest.service import GuestAccessLookup, MessengerGuestService


class MaxGuestService(MessengerGuestService):
    binding_model = MaxGuestBindingModel
    binding_user_field = "max_user_id"
    face_user_field = "max_user_id"
    channel_label = "MAX"

    def get_bound_guest_accesses(
        self,
        *,
        max_user_id: str,
    ) -> list[GuestAccessLookup]:
        return self._get_bound_guest_accesses(channel_user_id=max_user_id)

    def bind_guest_booking(
        self,
        *,
        reservation_code: str,
        max_user_id: str,
    ) -> dict[str, str]:
        return self._bind_guest_booking(
            reservation_code=reservation_code,
            channel_user_id=max_user_id,
        )

    def unbind_guest_booking(
        self,
        *,
        reservation_code: str,
        max_user_id: str,
    ) -> dict[str, str]:
        return self._unbind_guest_booking(
            reservation_code=reservation_code,
            channel_user_id=max_user_id,
        )

    def save_face_photo(
        self,
        *,
        reservation_code: str,
        guest_query: str,
        max_user_id: str,
        photo_bytes: bytes,
        content_type: str,
    ) -> dict[str, object]:
        return self._save_face_photo(
            reservation_code=reservation_code,
            guest_query=guest_query,
            channel_user_id=max_user_id,
            photo_bytes=photo_bytes,
            content_type=content_type,
        )
