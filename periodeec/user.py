class User:
    def __init__(self, id: str, name="", url="", uri=""):
        self.id = id
        self.name = name
        self.url = url
        self.uri = uri

    def __str__(self):
        return f"User(id={self.id}, name={self.name}, url={self.url}, uri={self.uri})"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "uri": self.uri
        }
