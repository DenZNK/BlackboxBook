#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PDF_PATH="$SCRIPT_DIR/BlackboxBook_phone.pdf"

cd "$SCRIPT_DIR" || exit 1

printf "Building phone PDF...\n\n"

if ! command -v python3 >/dev/null 2>&1; then
  printf "python3 was not found in PATH.\n\n"
  printf "Press Enter to close..."
  read -r _
  exit 1
fi

python3 "$SCRIPT_DIR/scripts/build_book_pdf.py" \
  --source "$SCRIPT_DIR/book" \
  --output "$PDF_PATH" \
  --page-width 4.1in \
  --page-height 9.1in \
  --margin 0.28in \
  --wrap-code-blocks \
  --code-font-size footnotesize
STATUS=$?

printf "\n"

if [ "$STATUS" -eq 0 ]; then
  printf "phone PDF created: %s\n" "$PDF_PATH"
else
  printf "Build failed with exit code %s\n" "$STATUS"
fi

printf "\nPress Enter to close..."
read -r _

exit "$STATUS"
