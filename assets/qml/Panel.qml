import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons

Item {
    id: root
    property var shell: null
    property var plugins: []
    property string message: "Loading…"
    property bool closingFromHost: false

    function open(payloadJson) { closingFromHost = false; window.visible = true; refresh.running = true }
    function close() { closingFromHost = true; window.visible = false; closingFromHost = false }
    function requestClose() {
        if (shell && typeof shell.hide === "function") shell.hide("io.github.oldjobobo.thpm")
        else window.visible = false
    }
    function refreshState() {
        try {
            var state = JSON.parse(stateOutput.text)
            plugins = state.plugins || []
            message = state.summary || ""
        } catch (error) { message = "Unable to read THPM state" }
    }
    function setPlugin(id, enabled) {
        mutate.command = ["thpm", "--json", "plugin", enabled ? "enable" : "disable", id]
        mutate.running = true
    }

    Process {
        id: refresh
        command: ["thpm", "--json", "ui", "state"]
        stdout: StdioCollector { id: stateOutput; onStreamFinished: root.refreshState() }
    }
    Process {
        id: mutate
        stdout: StdioCollector { onStreamFinished: refresh.running = true }
    }

    FloatingWindow {
        id: window
        visible: false
        title: "Theme Hook Plugins"
        implicitWidth: 720
        implicitHeight: 680
        color: Color.background
        onVisibleChanged: if (!visible && !root.closingFromHost) root.requestClose()

        Rectangle {
            anchors.fill: parent
            color: Color.background
            border.color: Color.accent
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Theme Hook Plugins"; color: Color.foreground; font.pixelSize: 22; font.bold: true }
                    Item { Layout.fillWidth: true }
                    Button { text: "Refresh"; onClicked: refresh.running = true }
                    Button { text: "Close"; onClicked: root.requestClose() }
                }
                Label { text: root.message; color: Color.foreground; opacity: 0.7 }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    ListView {
                        model: root.plugins
                        spacing: 6
                        delegate: Rectangle {
                            required property var modelData
                            width: ListView.view.width
                            height: modelData.ownership === "native" ? 56 : 72
                            radius: 6
                            color: modelData.enabled ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.12) : Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.04)
                            border.color: modelData.warnings.length ? Color.urgent : Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.18)
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Label { text: modelData.label; color: Color.foreground; font.bold: true }
                                    Label { text: modelData.description; color: Color.foreground; opacity: 0.65; elide: Text.ElideRight; Layout.fillWidth: true }
                                }
                                Label { visible: modelData.ownership === "native"; text: "Omarchy native"; color: Color.accent }
                                Switch {
                                    visible: modelData.ownership !== "native"
                                    checked: modelData.enabled
                                    enabled: modelData.available && !mutate.running
                                    onClicked: root.setPlugin(modelData.id, checked)
                                }
                            }
                        }
                    }
                }
            }
        }
        Shortcut { sequence: "Escape"; onActivated: root.requestClose() }
    }
}
