# Standalone development environment pinned to Neuromancer's verified nixpkgs.
let
  # Stable builtins only: nix-shell must not require flakes or fetch-tree.
  source = builtins.fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/e7439b6b14ad3cc35d05608ebca9bce01a25f5f8.tar.gz";
    sha256 = "sha256-H83yz/do+hjOO0uujHyH8RgtIQP2v7Mw+cLwcZK/xKc=";
  };
  pkgs = import source { };
  python = pkgs.python3.withPackages (ps: [ ps.rich ps.textual ps.setuptools ps.build ps.wheel ]);
in
pkgs.mkShellNoCC {
  packages = [ python pkgs.bash pkgs.git ];
  shellHook = ''
    export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
  '';
}
