#!/usr/bin/env python3
"""Convenience entrypoint: `python find_reviewers.py --article articles/<spec>.json`
(identical to `python -m reviewer_id`)."""
import sys

from reviewer_id.cli import main

if __name__ == "__main__":
    sys.exit(main())
