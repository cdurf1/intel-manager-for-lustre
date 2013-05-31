/*! sprintf.js | Copyright (c) 2007-2013 Alexandru Marasteanu <hello at alexei dot ro> | 3 clause BSD license */

(function () {
  'use strict';

  if (!String.prototype.sprintf) {
    String.prototype.sprintf = (function () {
      function get_type(variable) {
        return Object.prototype.toString.call(variable).slice(8, -1).toLowerCase();
      }
      function str_repeat(input, multiplier) {
        for (var output = []; multiplier > 0; output[--multiplier] = input) {/* do nothing */}
        return output.join('');
      }

      var str_format = function() {
        if (!str_format.cache.hasOwnProperty(this)) {
          str_format.cache[this] = str_format.parse(this);
        }
        Array.prototype.unshift.call(arguments, this);
        return str_format.format.call(null, str_format.cache[this], arguments);
      };

      str_format.format = function(parse_tree, argv) {
        var cursor = 1, tree_length = parse_tree.length, node_type = '', arg, output = [], i, k, match, pad, pad_character, pad_length;
        for (i = 0; i < tree_length; i++) {
          node_type = get_type(parse_tree[i]);
          if (node_type === 'string') {
            output.push(parse_tree[i]);
          }
          else if (node_type === 'array') {
            match = parse_tree[i]; // convenience purposes only
            if (match[2]) { // keyword argument
              arg = argv[cursor];
              for (k = 0; k < match[2].length; k++) {
                if (!arg.hasOwnProperty(match[2][k])) {
                  throw('[format] property "%s" does not exist'.format(match[2][k]));
                }
                arg = arg[match[2][k]];
              }
            }
            else if (match[1]) { // positional argument (explicit)
              arg = argv[match[1]];
            }
            else { // positional argument (implicit)
              arg = argv[cursor++];
            }

            if (/[^s]/.test(match[8]) && (get_type(arg) != 'number')) {
              throw('[format] expecting number but found %s'.format(get_type(arg)));
            }
            switch (match[8]) {
              case 'b': arg = arg.toString(2); break;
              case 'c': arg = String.fromCharCode(arg); break;
              case 'd': arg = parseInt(arg, 10); break;
              case 'e': arg = match[7] ? arg.toExponential(match[7]) : arg.toExponential(); break;
              case 'f': arg = match[7] ? parseFloat(arg).toFixed(match[7]) : parseFloat(arg); break;
              case 'o': arg = arg.toString(8); break;
              case 's': arg = ((arg = String(arg)) && match[7] ? arg.substring(0, match[7]) : arg); break;
              case 'u': arg = Math.abs(arg); break;
              case 'x': arg = arg.toString(16); break;
              case 'X': arg = arg.toString(16).toUpperCase(); break;
            }
            arg = (/[def]/.test(match[8]) && match[3] && arg >= 0 ? '+'+ arg : arg);
            pad_character = match[4] ? match[4] == '0' ? '0' : match[4].charAt(1) : ' ';
            pad_length = match[6] - String(arg).length;
            pad = match[6] ? str_repeat(pad_character, pad_length) : '';
            output.push(match[5] ? arg + pad : pad + arg);
          }
        }
        return output.join('');
      };

      str_format.cache = {};

      str_format.parse = function(fmt) {
        var _fmt = fmt, match = [], parse_tree = [], arg_names = 0;
        while (_fmt) {
          if ((match = /^[^\x25]+/.exec(_fmt)) !== null) {
            parse_tree.push(match[0]);
          }
          else if ((match = /^\x25{2}/.exec(_fmt)) !== null) {
            parse_tree.push('%');
          }
          else if ((match = /^\x25(?:([1-9]\d*)\$|\(([^\)]+)\))?(\+)?(0|'[^$])?(-)?(\d+)?(?:\.(\d+))?([b-fosuxX])/.exec(_fmt)) !== null) {
            if (match[2]) {
              arg_names |= 1;
              var field_list = [], replacement_field = match[2], field_match = [];
              if ((field_match = /^([a-z_][a-z_\d]*)/i.exec(replacement_field)) !== null) {
                field_list.push(field_match[1]);
                while ((replacement_field = replacement_field.substring(field_match[0].length)) !== '') {
                  if ((field_match = /^\.([a-z_][a-z_\d]*)/i.exec(replacement_field)) !== null) {
                    field_list.push(field_match[1]);
                  }
                  else if ((field_match = /^\[(\d+)\]/.exec(replacement_field)) !== null) {
                    field_list.push(field_match[1]);
                  }
                  else {
                    throw('[format] huh?');
                  }
                }
              }
              else {
                throw('[format] huh?');
              }
              match[2] = field_list;
            }
            else {
              arg_names |= 2;
            }
            if (arg_names === 3) {
              throw('[format] mixing positional and named placeholders is not (yet) supported');
            }
            parse_tree.push(match);
          }
          else {
            throw('[format] huh?');
          }
          _fmt = _fmt.substring(match[0].length);
        }
        return parse_tree;
      };

      return str_format;
    })();
  }

  if (!String.prototype.vsprintf) {
    String.prototype.vsprintf = function (argv) {
      return this.sprintf.apply(this, argv);
    };
  }
}());