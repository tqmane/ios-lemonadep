/*
 * libredwood-weather.dylib: Weather's forecast, from a server of ours (build.sh's INJECT names the
 * program; see inject.c for how the library gets into it).
 *
 * WeatherCore, the framework behind the Weather app, ships an environment of Apple's own called
 * "Local - Mock Server": weatherDataEndpointUrl http://localhost:5033, plain HTTP, no Mescal
 * signature, no TLS. Three defaults keys choose it --
 *
 *      weather.environment.contentEnvironment     "Local - Mock Server"
 *      weather.environment.localServerURL         "http://localhost"
 *      weather.environment.localServerPort        5033
 *
 * -- and this library is inside the app's own process, so setting them in a constructor happens
 * before anything has read them, which an environment variable or a preferences file cannot promise.
 * The paths the app then asks that port for are built at run time and are nowhere in the cache, so
 * the server below writes down every request it is given and answers with /var/redwood/weather.json
 * when that file is there and {} when it is not. One boot then says which paths, in which order,
 * what the headers are, and what the decoder complains about.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define PORT            5033
#define SNAPSHOT        "/var/mobile/redwood-weather.json"
#define MAX_REQUEST     8192
#define MAX_BODY        (1024 * 1024)

static int console = -1;

static void
say(const char *text, size_t length)
{
	if (console < 0) {
		console = open("/dev/console", O_WRONLY);
	}
	(void)write(console >= 0 ? console : 2, text, length);
}

static void
sayf(const char *format, ...)
{
	char line[1200];
	va_list arguments;
	int n;

	va_start(arguments, format);
	n = vsnprintf(line, sizeof(line), format, arguments);
	va_end(arguments);
	if (n > 0) {
		say(line, (size_t)(n < (int)sizeof(line) ? n : (int)sizeof(line) - 1));
	}
}

/* One defaults key, in the domain the app reads and in the one it was launched under. */
static void
set_pref(CFStringRef key, CFTypeRef value)
{
	char shown[200] = "";

	CFPreferencesSetAppValue(key, value, CFSTR("com.apple.weather"));
	CFPreferencesSetAppValue(key, value, kCFPreferencesCurrentApplication);
	CFPreferencesAppSynchronize(CFSTR("com.apple.weather"));
	(void)CFStringGetCString(key, shown, sizeof(shown), kCFStringEncodingUTF8);
	sayf("redwood: Weather: defaults %s set\n", shown);
}

/* The bytes of a file, or -1. */
static long
read_whole(const char *path, char *buffer, size_t size)
{
	int file = open(path, O_RDONLY);
	size_t used = 0;

	if (file < 0) {
		return -1;
	}
	for (;;) {
		ssize_t got = read(file, buffer + used, size - used);

		if (got <= 0) {
			break;
		}
		used += (size_t)got;
		if (used == size) {
			break;
		}
	}
	close(file);
	return (long)used;
}

static void
answer(int client)
{
	char request[MAX_REQUEST];
	static char body[MAX_BODY];
	size_t used = 0;
	char *headline, *path, *space;
	long length;
	char reply[300];

	/* The request head, up to the blank line: a request line and then the headers. */
	while (used < sizeof(request) - 1) {
		ssize_t got = read(client, request + used, sizeof(request) - 1 - used);

		if (got <= 0) {
			break;
		}
		used += (size_t)got;
		request[used] = 0;
		if (strstr(request, "\r\n\r\n") != NULL) {
			break;
		}
	}
	request[used] = 0;
	headline = request;
	/* The lines are separated by nulls from here on, so they can be printed one by one. */
	for (size_t i = 0; i < used; i++) {
		if (request[i] == '\r' || request[i] == '\n') {
			request[i] = 0;
		}
	}
	path = strchr(headline, ' ');
	if (path != NULL) {
		path++;
		space = strchr(path, ' ');
		if (space != NULL) {
			*space = 0;
		}
		sayf("redwood: Weather: the local server was asked for %s\n", path);
	} else {
		sayf("redwood: Weather: the local server was asked for %s\n", headline);
	}
	{
		char *line = headline + strlen(headline) + 1;

		while (line < request + used) {
			if (*line != 0) {
				sayf("redwood: Weather:   %s\n", line);
			}
			line += strlen(line) + 1;
		}
	}
	length = read_whole(SNAPSHOT, body, sizeof(body));
	if (length < 0) {
		memcpy(body, "{}", 2);
		length = 2;
		sayf("redwood: Weather: no %s, answering {}\n", SNAPSHOT);
	}
	(void)snprintf(reply, sizeof(reply),
	    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %ld\r\n"
	    "Connection: close\r\n\r\n", length);
	(void)write(client, reply, strlen(reply));
	(void)write(client, body, (size_t)length);
}

static void *
serve(void *unused)
{
	int listener, on = 1;
	struct sockaddr_in address;

	(void)unused;
	listener = socket(AF_INET, SOCK_STREAM, 0);
	if (listener < 0) {
		sayf("redwood: Weather: no socket for the local server: %s\n", strerror(errno));
		return NULL;
	}
	(void)setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));
	memset(&address, 0, sizeof(address));
	address.sin_family = AF_INET;
	address.sin_port = htons(PORT);
	address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	if (bind(listener, (struct sockaddr *)&address, sizeof(address)) != 0 || listen(listener, 16) != 0) {
		sayf("redwood: Weather: the local server cannot have port %d: %s\n", PORT, strerror(errno));
		close(listener);
		return NULL;
	}
	sayf("redwood: Weather: the local server listens on 127.0.0.1:%d, answering %s\n", PORT, SNAPSHOT);
	for (;;) {
		int client = accept(listener, NULL, NULL);

		if (client < 0) {
			continue;
		}
		answer(client);
		close(client);
	}
}

__attribute__((constructor))
static void
redwood_weather_init(void)
{
	pthread_t thread;
	int number = PORT;
	CFNumberRef port = CFNumberCreate(NULL, kCFNumberIntType, &number);

	console = open("/dev/console", O_WRONLY);
	sayf("redwood: Weather: the local server is going into the environment Apple calls Local\n");
	set_pref(CFSTR("weather.environment.contentEnvironment"), CFSTR("Local - Mock Server"));
	set_pref(CFSTR("weather.environment.localServerURL"), CFSTR("http://localhost"));
	set_pref(CFSTR("weather.environment.localServerPort"), port);
	if (port != NULL) {
		CFRelease(port);
	}
	if (pthread_create(&thread, NULL, serve, NULL) != 0) {
		sayf("redwood: Weather: no thread for the local server: %s\n", strerror(errno));
	}
}
