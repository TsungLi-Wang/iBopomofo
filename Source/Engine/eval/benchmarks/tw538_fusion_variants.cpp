// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// DEAD KNOBS REMOVED (2026-07 internal cleanup).
// Death list: len_char / len_word / zscore / minmax fusion modes were fully
// grid-searched; best gain was only +1 sentence. Runtime tuning surface is gone.
// Historical numbers: eval/analysis/tw538-fusion-variants-table.md
// Full prior source: git history of this path before the cleanup commit.
//
// Intentionally non-runnable so knobs cannot be re-enabled by accident.

#include <iostream>

int main(int, char**) {
  std::cerr
      << "FATAL: tw538_fusion_variants knobs removed (death list: fusion "
         "formula len/zscore/minmax). See analysis/tw538-fusion-variants-table.md\n";
  return 3;
}
