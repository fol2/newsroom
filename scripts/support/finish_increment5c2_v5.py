"""Finish Increment 5C2 using the unique digest-selected patch bytes."""
from scripts.support.publish_increment5c2_final_review_v5 import main as publish
from scripts.support.finalize_increment5c2 import main as finalize


def main() -> None:
    publish()
    finalize()


if __name__ == "__main__":
    main()
