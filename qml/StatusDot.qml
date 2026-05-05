import QtQuick 2.7
import Lomiri.Components 1.3

Rectangle {
    property string status: "offline" // "online" | "idle" | "dnd" | "offline" | "invisible"

    width:  units.gu(1.2)
    height: units.gu(1.2)

    color: {
        if (status === "online")    return "#23A55A"
        if (status === "idle")      return "#F0B232"
        if (status === "dnd")       return "#F23F43"
        return "#80848E" // offline / invisible / unknown
    }
}
