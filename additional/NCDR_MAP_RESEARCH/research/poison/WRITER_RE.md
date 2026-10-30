# Writer static review

`poison.exe` imports C stdio file I/O (`fopen`, `fread`, `fseek`, `fwrite`, `fflush`, `fclose`) and allocation/memory routines. This establishes file-based read/write capability, but does not by itself prove in-place versus rebuild behavior.
