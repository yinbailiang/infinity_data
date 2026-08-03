```sd
{
    a {
        b
        c
    }
    b {
        c
        d
    }
}
```
->
```json
{
    "a":{
        "b":null,
        "c":null
    },
    "b":{
        "c":null,
        "d":null
    }
}
```