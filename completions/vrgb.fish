# fish completion for vrgb

function __vrgb_colors
    printf "%s\n" red green blue yellow cyan magenta orange purple pink white warmwhite black
end

function __vrgb_last_arg_is_color
    set -l cmd (commandline -opc)
    test (count $cmd) -ge 2
    and contains -- $cmd[-1] color effect set
end

# top-level commands
complete -c vrgb -n "__fish_is_first_arg" -f -a "info color off auto effect daemon set" -d "vrgb subcommand"

# info/off/auto take no args
complete -c vrgb -n "__fish_seen_subcommand_from info off auto" -f

# color: any position -> color names (hex still typed by hand)
complete -c vrgb -n "__fish_seen_subcommand_from color" -f -a "(__vrgb_colors)"

# effect <mode> ...
complete -c vrgb -n "__fish_seen_subcommand_from effect; and __fish_is_first_arg" -f -a "breathe cycle fade"
complete -c vrgb -n "__fish_seen_subcommand_from effect; and not __fish_seen_subcommand_from breathe cycle fade" -f
complete -c vrgb -n "__fish_seen_subcommand_from effect breathe; and test (count (commandline -opc)) -lt 4" -f -a "(__vrgb_colors)"
complete -c vrgb -n "__fish_seen_subcommand_from effect fade; and test (count (commandline -opc)) -lt 4" -f -a "(__vrgb_colors)"
complete -c vrgb -n "__fish_seen_subcommand_from effect cycle" -f

# set <mode> ...
complete -c vrgb -n "__fish_seen_subcommand_from set; and __fish_is_first_arg" -f -a "color off auto breathe cycle fade"
complete -c vrgb -n "__fish_seen_subcommand_from set color" -f -a "(__vrgb_colors)"
complete -c vrgb -n "__fish_seen_subcommand_from set breathe; and test (count (commandline -opc)) -lt 4" -f -a "(__vrgb_colors)"
complete -c vrgb -n "__fish_seen_subcommand_from set fade; and test (count (commandline -opc)) -lt 4" -f -a "(__vrgb_colors)"
complete -c vrgb -n "__fish_seen_subcommand_from set off auto cycle" -f
