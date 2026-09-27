// Native executable for Watchbar.app. macOS grants Full Disk Access to the
// app's own binary and extends it to child processes, so the launcher spawns
// Python as a child and stays alive. Exec'ing into Python would make the
// process Python's, which does not hold the grant.
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t child;

static void forward(int sig) {
    if (child > 0)
        kill(child, sig);
}

int main(void) {
    char path[4096];
    const char *old_path = getenv("PATH");
    snprintf(path, sizeof path, "/opt/homebrew/bin:/usr/local/bin:%s",
             old_path ? old_path : "/usr/bin:/bin:/usr/sbin:/sbin");
    setenv("PATH", path, 1);

    if (chdir(REPO) != 0)
        return 1;

    char log_path[1024];
    snprintf(log_path, sizeof log_path, "%s/Library/Logs/Watchbar.log",
             getenv("HOME"));
    int fd = open(log_path, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd >= 0) {
        dup2(fd, STDOUT_FILENO);
        dup2(fd, STDERR_FILENO);
        close(fd);
    }

    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);

    char *argv[] = {".venv/bin/python", "-u", "app.py", NULL};
    if (posix_spawn(&child, argv[0], NULL, NULL, argv, environ) != 0)
        return 1;

    int status;
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
