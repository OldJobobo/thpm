# Standalone development environment pinned to Neuromancer's verified nixpkgs.
let
  source = builtins.fetchTree {
    type = "github";
    owner = "NixOS";
    repo = "nixpkgs";
    rev = "e7439b6b14ad3cc35d05608ebca9bce01a25f5f8";
    narHash = "sha256-H83yz/do+hjOO0uujHyH8RgtIQP2v7Mw+cLwcZK/xKc=";
  };
  pkgs = import source.outPath { };
  python = pkgs.python3.withPackages (ps: [ ps.rich ps.textual ps.setuptools ps.build ps.wheel ]);
in
pkgs.mkShellNoCC {
  packages = [ python pkgs.bash pkgs.git ];
  shellHook = ''
    export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
  '';
}
