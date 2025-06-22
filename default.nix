let
  nixpkgs_unstable = fetchTarball "https://github.com/NixOS/nixpkgs/tarball/nixos-unstable";
  pkgs_unstable = import nixpkgs_unstable { config = {}; overlays = []; };
  pkgs = import <nixpkgs> { };
in
pkgs.mkShell {
  name = "config-shell";
  nativeBuildInputs = with pkgs; [
    git
    # python
    pkgs_unstable.python313
    pkgs_unstable.python313Packages.pip
    pkgs_unstable.python313Packages.virtualenv
    # python package manager
    pkgs_unstable.uv
    # format
    nixfmt-rfc-style
    ruff
  ];

  shellHook = ''
    source "$PWD/.env"

    export PATH=$PWD/.venv/bin/:$PATH
    export PYTHONPATH=$PWD/.venv/:$PYTHONPATH
    export RUFF=${pkgs.ruff}/bin/ruff

    export UV_NO_SYNC="1";
    export UV_PYTHON="${pkgs_unstable.python313}/bin/python";
    export UV_PYTHON_DOWNLOADS="never";
  '';
}
