$1 == expected ":" && $2 == "digest:" {
  matches += 1
  valid = NF == 5 && length($3) == 71 && $3 ~ /^sha256:[a-f0-9]+$/
  valid = valid && $4 == "size:" && $5 ~ /^[0-9]+$/
  if (valid) {
    digest = $3
  } else {
    invalid = 1
  }
}

END {
  if (matches != 1 || invalid || digest == "") {
    exit 1
  }
  print digest
}
