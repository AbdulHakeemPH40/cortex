"use strict";

var QWebChannelMessageTypes = {
    Init: 1,
    Idle: 2,
    MsgToQt: 3,
    MsgToJs: 4,
    Signal: 5,
    Response: 6,
    PropertyUpdate: 7,
    ObjectDestroyed: 8,
    InitByJs: 9
};

var QWebChannel = function(transport, initCallback)
{
    if (typeof transport !== "object" || typeof transport.send !== "function") {
        console.error("The QWebChannel: provided transport is not an object, or does not have a send function.");
        return;
    }

    var channel = this;
    this.transport = transport;

    this.send = function(data)
    {
        if (typeof data !== "string") {
            data = JSON.stringify(data);
        }
        channel.transport.send(data);
    }

    this.transport.onmessage = function(message)
    {
        var data = message.data;
        if (typeof data === "string") {
            data = JSON.parse(data);
        }
        switch (data.type) {
            case QWebChannelMessageTypes.Signal:
                channel.handleSignal(data);
                break;
            case QWebChannelMessageTypes.Response:
                channel.handleResponse(data);
                break;
            case QWebChannelMessageTypes.PropertyUpdate:
                channel.handlePropertyUpdate(data);
                break;
            case QWebChannelMessageTypes.ObjectDestroyed:
                channel.handleObjectDestroyed(data);
                break;
        }
    };

    this.execCallbacks = {};
    this.execId = 0;
    this.exec = function(data, callback)
    {
        if (!callback) {
            channel.send(data);
            return;
        }
        var id = channel.execId++;
        channel.execCallbacks[id] = callback;
        data.id = id;
        channel.send(data);
    };

    this.handleResponse = function(data)
    {
        if (!data.hasOwnProperty("id")) {
            console.error("Invalid response received: ", data);
            return;
        }
        if (channel.execCallbacks.hasOwnProperty(data.id)) {
            channel.execCallbacks[data.id](data.res);
            delete channel.execCallbacks[data.id];
        }
    };

    this.dragHandler = function(e)
    {
        e.preventDefault();
    };

    this.handleSignal = function(data)
    {
        var object = channel.objects[data.object];
        if (object) {
            object.signals[data.signal].emit.apply(object.signals[data.signal], data.args);
        }
    };

    this.handlePropertyUpdate = function(data)
    {
        for (var i in data.signals) {
            var signal = data.signals[i];
            channel.handleSignal(signal);
        }
        for (var i in data.properties) {
            var property = data.properties[i];
            channel.objects[property.object].properties[property.property] = property.value;
        }
    };

    this.handleObjectDestroyed = function(data)
    {
        delete channel.objects[data.object];
    };

    this.objects = {};

    this.debug = function(message)
    {
        console.log(message);
    };

    this.exec({type: QWebChannelMessageTypes.Init}, function(data) {
        for (var objectName in data) {
            var object = data[objectName];
            var instance = {
                id: objectName,
                signals: {},
                properties: {},
                methods: {}
            };

            for (var i in object.signals) {
                var signalName = object.signals[i];
                instance.signals[signalName] = {
                    emit: function() {
                        var args = Array.prototype.slice.call(arguments);
                        for (var j in this.connections) {
                            this.connections[j].apply(null, args);
                        }
                    },
                    connect: function(callback) {
                        this.connections.push(callback);
                    },
                    connections: []
                };
                instance[signalName] = instance.signals[signalName];
            }

            for (var i in object.properties) {
                var property = object.properties[i];
                instance.properties[property[0]] = property[1];
                instance[property[0]] = property[1];
            }

            for (var i in object.methods) {
                (function() {
                    var methodName = object.methods[i];
                    instance[methodName] = function() {
                        var args = Array.prototype.slice.call(arguments);
                        var callback = null;
                        if (args.length > 0 && typeof args[args.length - 1] === "function") {
                            callback = args.pop();
                        }
                        channel.exec({
                            type: QWebChannelMessageTypes.MsgToQt,
                            object: instance.id,
                            method: methodName,
                            args: args
                        }, callback);
                    };
                })();
            }

            channel.objects[objectName] = instance;
        }

        if (initCallback) {
            initCallback(channel);
        }
    });
};

if (typeof module !== 'undefined') {
    module.exports = {
        QWebChannel: QWebChannel
    };
}
