"""Reassemble the final 5C2 correction from exact small, hashed chunks."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from scripts.support import publish_increment5c2_final_review as builder

PARTS: tuple[tuple[str, int, str], ...] = (
    ("increment5c2_final_review.patch.b64.part00", 8500, "d5cb7f34c4f3ff61a7013be3a4410c1a51e2e54f6e8184c3d200b9eec1e78488"),
    ("increment5c2_final_review.patch.b64.part01.00", 1000, "816029d3043b71d6112bd5a591a9a490c205b6dfd6e22bd3675ade4181db3b19"),
    ("increment5c2_final_review.patch.b64.part01.01", 1000, "1fdbb2289d496e96b1043d71632256b98faf4525f869358a2f913f25a2c99fd4"),
    ("increment5c2_final_review.patch.b64.part01.02", 1000, "d0af4662e1578890e7418392ed24fee7c0bc7a93406ef993444f53e835ba8eef"),
    ("increment5c2_final_review.patch.b64.part01.03", 1000, "ddbd90ae07124f1866dd638dd4bed156f1109ea00adf22c6aa2fd1462271ad39"),
    ("increment5c2_final_review.patch.b64.part01.04", 1000, "88581b04b70091cfe5e074deba549eb73ae59834debe55955c0d8fc33fb7ad4c"),
    ("increment5c2_final_review.patch.b64.part01.05", 1000, "7381b269e1a802aca61f2956384d2afb2953f47497adbceeb4e63be812e0a5c1"),
    ("increment5c2_final_review.patch.b64.part01.06", 1000, "1a25692d8ef47adba18da85ceb533043c5909b9fc2c4488a901a7d1fa9b0df3b"),
    ("increment5c2_final_review.patch.b64.part01.07", 1000, "85435ba94da868e9b03f05d0a8117b750611c25b306adf418142049a6b8d395f"),
    ("increment5c2_final_review.patch.b64.part01.08", 500, "b2e6a8ae13a37811a9a327ac9ec2c9c2ee1bdc3652ccfffedc00cf33a5447f8d"),
    ("increment5c2_final_review.patch.b64.part02.00", 1000, "613799f91358092a07cd88c535a9e066c70d9dea85cc273f4cbd71bf37ce88e4"),
    ("increment5c2_final_review.patch.b64.part02.01", 1000, "a54c2d382183f95edb337a0aee1bb786fe84149184454a581b2b3341aeaf8c5c"),
    ("increment5c2_final_review.patch.b64.part02.02", 1000, "f72cf3fba738ebe5f7bd3de1d1512178584b46f6ad036490053cbb38b8cd212b"),
    ("increment5c2_final_review.patch.b64.part02.03", 1000, "b9ff8707a922fcfdf7c3bbcdb428ecfd0715588e3442cc73f16c8814d0154bda"),
    ("increment5c2_final_review.patch.b64.part02.04", 1000, "edc03a4ad53d16272c63f255eb8116d685d32eff9fe3e2fb6eb87f971823c896"),
    ("increment5c2_final_review.patch.b64.part02.05", 1000, "d172384372ccc132b6ebc64db9be25a4125e63ff52d59c98e62a4a0002bac7bd"),
    ("increment5c2_final_review.patch.b64.part02.06", 1000, "7a8cce9aa570bbcdc1a319cc9e6c7f5970502b5a049b099dbaec4c3dfb5d6da7"),
    ("increment5c2_final_review.patch.b64.part02.07", 1000, "68d66df7641c31c1ea3c8359e0de7753b9f873e191aea278ece94883630e3f56"),
    ("increment5c2_final_review.patch.b64.part02.08", 500, "2a174c1f4687c09fcb0de6242b306e69368a82ff55f9056df6a3a4610b8c1131"),
    ("increment5c2_final_review.patch.b64.part03", 8500, "418728c90a80b16dbc429ff6a9c86218008f62682cd134f8ec3aff42a2ec3c77"),
    ("increment5c2_final_review.patch.b64.part04", 8500, "0357c6bfff3c1f2d73a7cd2705ecfc6545a8f7887e953e727e4be5d3d9cede6b"),
    ("increment5c2_final_review.patch.b64.part05.00", 1000, "f3e690ba50919bf131ddc27017d21bb793fb4f6ae5aba8dafa2c6ce1f013d3c2"),
    ("increment5c2_final_review.patch.b64.part05.01", 1000, "e7ac9d74704ac2a78ee6a474ba4fd1b6ff1c3eb445f1e693ccf3c0c17a41a290"),
    ("increment5c2_final_review.patch.b64.part05.02", 1000, "b57f82a9068656461ac0e3914444fef28a76869844d8237c25ca04c83008ceb4"),
    ("increment5c2_final_review.patch.b64.part05.03", 1000, "3a62cd65dc288862921b0c347a0655b78dd7dfff049e5dd4c835dfa3b5c6328e"),
    ("increment5c2_final_review.patch.b64.part05.04", 1000, "c2530443e7c981287361d8a920cc0a05f2e7e6e45f884558c834234b1db146b2"),
    ("increment5c2_final_review.patch.b64.part05.05", 1000, "629063b84aad4d457f3d15d02c9e3dd2d918e602f3a5ef5af73244297c155ce6"),
    ("increment5c2_final_review.patch.b64.part05.06", 1000, "bf833f1f9ec902b95f96ad9188006d5822d10d88fd5cba749ebfb5e7101d4de1"),
    ("increment5c2_final_review.patch.b64.part05.07", 1000, "0cf7de69c5c30667ca257f1fc5b57caab146fc2b61a01bfe77ec4356632a81a9"),
    ("increment5c2_final_review.patch.b64.part05.08", 500, "4627b461642d8265160be91c32568110a8527a1853aacea3a26bb7ef631504b9"),
    ("increment5c2_final_review.patch.b64.part06", 764, "50052cac1fdfdb66e8bb2652076742e5307fdcb83007f80c09c9e976ccccaeb4"),
)


def rebuild_patch() -> None:
    encoded_parts: list[str] = []
    for name, expected_size, expected_sha256 in PARTS:
        path = builder.PART_ROOT / name
        if not path.is_file():
            raise SystemExit(f"final review patch chunk is absent: {name}")
        raw = path.read_bytes()
        if len(raw) != expected_size:
            raise SystemExit(
                f"final review patch chunk size drifted: {name}: {len(raw)}"
            )
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != expected_sha256:
            raise SystemExit(
                f"final review patch chunk digest drifted: {name}: {actual_sha256}"
            )
        encoded_parts.append("".join(raw.decode("ascii").split()))
    try:
        patch = base64.b64decode("".join(encoded_parts), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SystemExit("final review patch chunks are not valid base64") from exc
    actual_patch_sha256 = hashlib.sha256(patch).hexdigest()
    if actual_patch_sha256 != builder.EXPECTED_PATCH_SHA256:
        raise SystemExit(
            "final review decoded patch digest mismatch: "
            f"{actual_patch_sha256}"
        )
    builder.PATCH_PATH.write_bytes(patch)


def main() -> None:
    builder.rebuild_patch = rebuild_patch
    builder.main()


if __name__ == "__main__":
    main()
